import json
import uuid
import asyncio
from types import SimpleNamespace

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized
from pydantic import ValidationError

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import (
    _PROJECT_ROOT_PREFIX,
    _SOURCE_SKIP_PREFIXES,
    AccessMethod,
    DagsterTags,
    Feature,
    HogQLFeatures,
    Product,
    QueryTags,
    TemporalTags,
    add_fallback_query_tags,
    clear_tag,
    create_base_tags,
    get_caller_source,
    get_query_tag_value,
    get_query_tags,
    is_api_key_access_method,
    reset_query_tags,
    tag_contains_user_hogql,
    tag_queries,
    tags_context,
    update_tags,
)


def test_create_base_tags():
    qt = create_base_tags(container_hostname="my-new-hostname")
    assert qt.container_hostname == "test"


def test_with_temporal():
    qt = create_base_tags()
    qt.with_temporal(TemporalTags(workflow_type="wt"))
    assert qt.model_dump(exclude_none=True) == {
        "container_hostname": "test",
        "git_commit": "test",
        "kind": "temporal",
        "service_name": "test",
        "temporal": {"workflow_type": "wt"},
    }


def test_simple_query_tags():
    uid = uuid.UUID("f3065cb7-10a5-4707-8910-a7c777896ac8")
    qt = QueryTags(
        team_id=1,
        name="my name",
        product=Product.API,
        http_request_id=uid,
        git_commit="",
        container_hostname="",
        service_name="",
    )
    assert qt.team_id == 1
    assert qt.user_id is None
    assert qt.org_id is None
    assert qt.name == "my name"
    assert qt.access_method is None
    assert qt.product == "api"
    assert qt.http_request_id == uid

    data = qt.to_json()
    assert (
        data
        == '{"team_id":1,"product":"api","name":"my name","http_request_id":"f3065cb7-10a5-4707-8910-a7c777896ac8","git_commit":"","container_hostname":"","service_name":""}'
    )


def test_constant_tags():
    want = QueryTags(git_commit="test", container_hostname="test", service_name="test")
    assert create_base_tags() == want
    reset_query_tags()
    assert get_query_tags() == want


def test_set_get():
    reset_query_tags()
    tag_queries(team_id=1, product=Product.API)

    assert get_query_tag_value("team_id") == 1
    assert get_query_tag_value("product") == "api"


def test_failure_on_incorrect_type():
    reset_query_tags()
    with pytest.raises(ValidationError):
        tag_queries(team_id="jeden")
    assert get_query_tags() == create_base_tags()


def test_session_id_accepts_non_uuid_strings():
    reset_query_tags()
    tag_queries(session_id="not-a-uuid-but-valid-string")
    tags = get_query_tags()
    assert tags.session_id == "not-a-uuid-but-valid-string"


def test_clear_tag():
    reset_query_tags()
    clear_tag("team_id")
    assert get_query_tags() == create_base_tags()
    reset_query_tags()
    assert get_query_tags() == create_base_tags()
    tag_queries(team_id=123)
    assert get_query_tags() == create_base_tags(team_id=123)
    clear_tag("user_id")
    assert get_query_tags() == create_base_tags(team_id=123)
    clear_tag("team_id")
    assert get_query_tags() == create_base_tags()


def test_tags_context():
    reset_query_tags()
    # Set initial tags
    tag_queries(team_id=123)
    assert get_query_tags() == create_base_tags(team_id=123)

    # Modify tags within context
    with tags_context(user_id=312):
        tag_queries(cohort_id=777)
        assert get_query_tags() == create_base_tags(team_id=123, user_id=312, cohort_id=777)

        # Modify more
        tag_queries(name="another_value", team_id=1234)
        assert get_query_tags() == create_base_tags(team_id=1234, user_id=312, cohort_id=777, name="another_value")

    # Verify tags are restored
    assert get_query_tags() == create_base_tags(team_id=123)


def test_tags_context_snapshot_isolation():
    # Shallow-copy invariant: mutations through public helpers must not corrupt the
    # saved snapshot that tags_context restores. Regression guard for the switch from
    # deep to shallow model_copy in update_tags/tag_queries.
    reset_query_tags()
    tag_queries(team_id=1)

    with tags_context(user_id=42):
        snapshot = get_query_tags()
        # Drive every public mutation helper after the snapshot is taken.
        tag_queries(team_id=2)
        update_tags(create_base_tags(cohort_id=99))
        clear_tag("user_id")
        qt = get_query_tags()
        qt.with_temporal(TemporalTags(workflow_type="wt"))
        qt.with_dagster(DagsterTags(run_id="run-1"))

    # The snapshot taken inside tags_context must be untouched by all mutations above.
    assert snapshot == create_base_tags(team_id=1, user_id=42)


@pytest.mark.asyncio
async def test_async_tasks_have_isolated_tags():
    reset_query_tags()

    # Use Events to guarantee interleaved execution
    task_a_set_tags = asyncio.Event()
    task_b_set_tags = asyncio.Event()

    results = {}

    async def task_a():
        # Task A sets its tags first
        tag_queries(team_id=100, user_id=1)
        task_a_set_tags.set()

        # Wait for Task B to set its tags
        await task_b_set_tags.wait()

        tags = get_query_tags()
        results["task_a"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    async def task_b():
        # Wait for Task A to set its tags first
        await task_a_set_tags.wait()

        # Task B sets its own tags (after Task A)
        tag_queries(team_id=200, user_id=2)
        task_b_set_tags.set()

        tags = get_query_tags()
        results["task_b"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    task_a_handle = asyncio.create_task(task_a())
    task_b_handle = asyncio.create_task(task_b())

    await task_a_handle
    await task_b_handle

    # Each task should see its own values, not contaminated by the other
    assert results["task_a"]["team_id"] == 100
    assert results["task_a"]["user_id"] == 1

    assert results["task_b"]["team_id"] == 200
    assert results["task_b"]["user_id"] == 2


@pytest.mark.asyncio
async def test_async_tasks_have_isolated_tags_with_update_tags():
    reset_query_tags()

    # Use Events to guarantee interleaved execution
    task_a_set_tags = asyncio.Event()
    task_b_set_tags = asyncio.Event()

    results = {}

    async def task_a():
        # Task A updates its tags first
        tags_to_update = QueryTags(team_id=100, user_id=1)
        update_tags(tags_to_update)
        task_a_set_tags.set()

        # Wait for Task B to update its tags
        await task_b_set_tags.wait()

        tags = get_query_tags()
        results["task_a"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    async def task_b():
        # Wait for Task A to update its tags first
        await task_a_set_tags.wait()

        # Task B updates its own tags (after Task A)
        tags_to_update = QueryTags(team_id=200, user_id=2)
        update_tags(tags_to_update)
        task_b_set_tags.set()

        tags = get_query_tags()
        results["task_b"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    task_a_handle = asyncio.create_task(task_a())
    task_b_handle = asyncio.create_task(task_b())

    await task_a_handle
    await task_b_handle

    # Each task should see its own values, not contaminated by the other
    assert results["task_a"]["team_id"] == 100
    assert results["task_a"]["user_id"] == 1

    assert results["task_b"]["team_id"] == 200
    assert results["task_b"]["user_id"] == 2


@pytest.mark.asyncio
async def test_async_tasks_have_isolated_tags_with_clear_tag():
    reset_query_tags()

    # Both tasks start with same initial tags
    tag_queries(team_id=100, user_id=50)

    # Use Events to guarantee interleaved execution
    task_a_cleared = asyncio.Event()
    task_b_cleared = asyncio.Event()

    results = {}

    async def task_a():
        # Task A clears user_id
        clear_tag("user_id")
        task_a_cleared.set()

        # Wait for Task B to clear team_id
        await task_b_cleared.wait()

        tags = get_query_tags()
        results["task_a"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    async def task_b():
        # Wait for Task A to clear user_id
        await task_a_cleared.wait()

        # Task B clears team_id (after Task A)
        clear_tag("team_id")
        task_b_cleared.set()

        tags = get_query_tags()
        results["task_b"] = {"team_id": tags.team_id, "user_id": tags.user_id}

    task_a_handle = asyncio.create_task(task_a())
    task_b_handle = asyncio.create_task(task_b())

    await task_a_handle
    await task_b_handle

    # Task A cleared user_id, should still have team_id
    assert results["task_a"]["team_id"] == 100
    assert results["task_a"]["user_id"] is None

    # Task B cleared team_id, should still have user_id
    assert results["task_b"]["team_id"] is None
    assert results["task_b"]["user_id"] == 50


def test_get_caller_source_returns_this_file():
    source_file, source_line = get_caller_source()
    assert source_file == "posthog/clickhouse/test/test_query_tagging.py"
    assert source_line is not None


def test_get_caller_source_skips_infrastructure():
    for prefix in _SOURCE_SKIP_PREFIXES:
        assert prefix.startswith(_PROJECT_ROOT_PREFIX)


def test_tag_contains_user_hogql_sets_flag():
    reset_query_tags()
    assert get_query_tag_value("contains_user_hogql") is None
    tag_contains_user_hogql()
    assert get_query_tag_value("contains_user_hogql") is True


def test_tag_contains_user_hogql_is_idempotent():
    reset_query_tags()
    tag_contains_user_hogql()
    tag_contains_user_hogql()
    assert get_query_tag_value("contains_user_hogql") is True


def test_tag_contains_user_hogql_short_circuits_after_first_call():
    # Repeated calls (recursive property_to_expr, breakdown loops, @property accessors)
    # must skip the model_copy() inside tag_queries after the first call.
    reset_query_tags()
    tag_contains_user_hogql()
    first_tags = get_query_tags()
    tag_contains_user_hogql()
    tag_contains_user_hogql()
    # Same object — no fresh copy was set by the no-op calls
    assert get_query_tags() is first_tags


def test_contains_user_hogql_excluded_from_json_when_none():
    qt = QueryTags(git_commit="test", container_hostname="test", service_name="test")
    assert "contains_user_hogql" not in qt.to_json()


def test_contains_user_hogql_included_in_json_when_set():
    qt = QueryTags(
        contains_user_hogql=True,
        git_commit="test",
        container_hostname="test",
        service_name="test",
    )
    assert '"contains_user_hogql":true' in qt.to_json()


def test_source_file_excluded_from_json_when_none():
    qt = QueryTags(git_commit="test", container_hostname="test", service_name="test")
    data = qt.to_json()
    assert "source_file" not in data
    assert "source_line" not in data


def test_source_file_included_in_json_when_set():
    qt = QueryTags(
        source_file="posthog/api/query.py",
        source_line=42,
        git_commit="test",
        container_hostname="test",
        service_name="test",
    )
    data = qt.to_json()
    assert '"source_file":"posthog/api/query.py"' in data
    assert '"source_line":42' in data


class TestQueryTaggingSourceInQueryLog(BaseTest, ClickhouseTestMixin):
    def _get_log_comment(self, marker: str) -> dict:
        sync_execute("SYSTEM FLUSH LOGS")
        rows = sync_execute(
            "SELECT log_comment FROM system.query_log "
            "WHERE query LIKE %(marker)s AND type = 'QueryFinish' "
            "ORDER BY event_time DESC LIMIT 1",
            {"marker": f"%{marker}%"},
        )
        assert rows, f"No query log entry found containing marker {marker}"
        return json.loads(rows[0][0])

    def test_sync_execute_populates_source_tags(self):
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test")
        sync_execute(f"SELECT '{marker}'")  # noqa: S608

        comment = self._get_log_comment(marker)

        assert comment["source_file"] == "posthog/clickhouse/test/test_query_tagging.py"
        assert comment["source_line"] > 0

    def test_execute_hogql_query_populates_source_tags(self):
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test")
        execute_hogql_query(f"SELECT '{marker}'", team=self.team, query_type="HogQLQuery")  # noqa: S608

        comment = self._get_log_comment(marker)

        assert comment["source_file"] == "posthog/clickhouse/test/test_query_tagging.py"
        assert comment["source_line"] > 0

    @parameterized.expand([("approved", True), ("not_approved", False)])
    def test_sync_execute_preserves_ai_data_processing_approved_tag(self, _name, approved):
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk, ai_data_processing_approved=approved)
        sync_execute(f"SELECT '{marker}'")  # noqa: S608

        comment = self._get_log_comment(marker)

        assert comment["ai_data_processing_approved"] is approved

    def test_sync_execute_omits_ai_data_processing_approved_when_not_tagged(self):
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk)
        sync_execute(f"SELECT '{marker}'")  # noqa: S608

        comment = self._get_log_comment(marker)

        assert "ai_data_processing_approved" not in comment

    def test_sync_execute_falls_back_to_mcp_product_when_source_is_mcp(self):
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk, source="mcp", feature="query")
        sync_execute(f"SELECT '{marker}'")  # noqa: S608

        comment = self._get_log_comment(marker)

        assert comment["product"] == Product.MCP.value

    def test_sync_execute_does_not_override_existing_product_when_source_is_mcp(self):
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(
            kind="request",
            id="test",
            team_id=self.team.pk,
            source="mcp",
            product=Product.LOGS,
            feature="query",
        )
        sync_execute(f"SELECT '{marker}'")  # noqa: S608

        comment = self._get_log_comment(marker)

        assert comment["product"] == Product.LOGS.value

    @parameterized.expand([("api", "api"), ("web", "web"), ("posthog_code", "posthog_code")])
    def test_sync_execute_does_not_set_mcp_product_when_source_is_not_mcp(self, _name, source):
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk, source=source, feature="query")
        sync_execute(f"SELECT '{marker}'")  # noqa: S608

        comment = self._get_log_comment(marker)

        assert comment.get("product") != Product.MCP.value

    def test_execute_hogql_query_populates_hogql_features_tag(self):
        # End-to-end: a HogQLQuery against `events` filtered by `$exception` should
        # land in query_log with both the AST-derived hogql_features tag and the
        # error_tracking product attribution that derives from it.
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk, feature="query")
        execute_hogql_query(
            f"SELECT count() FROM events WHERE distinct_id = '{marker}' AND event = '$exception'",  # noqa: S608
            team=self.team,
            query_type="HogQLQuery",
        )

        comment = self._get_log_comment(marker)

        assert comment["hogql_features"] == {"tables": ["events"], "events": ["$exception"]}
        assert comment["product"] == Product.ERROR_TRACKING.value

    def test_execute_hogql_query_attributes_plain_events_query_to_product_analytics(self):
        # Plain `events` query (no narrowing event filter) should fall back to
        # product_analytics via the table-level rule.
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk, feature="query")
        execute_hogql_query(
            f"SELECT count() FROM events WHERE distinct_id = '{marker}'",  # noqa: S608
            team=self.team,
            query_type="HogQLQuery",
        )

        comment = self._get_log_comment(marker)

        assert comment["hogql_features"] == {"tables": ["events"], "events": []}
        assert comment["product"] == Product.PRODUCT_ANALYTICS.value

    def test_hogql_query_runner_marks_contains_user_hogql(self):
        from posthog.schema import HogQLQuery

        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk, feature="query")

        runner = HogQLQueryRunner(query=HogQLQuery(query=f"SELECT '{marker}'"), team=self.team)  # noqa: S608
        runner._calculate()

        comment = self._get_log_comment(marker)
        assert comment.get("contains_user_hogql") is True

    def test_platform_query_does_not_mark_contains_user_hogql(self):
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk, feature="query", product=Product.INTERNAL)
        sync_execute(f"SELECT '{marker}'")  # noqa: S608

        comment = self._get_log_comment(marker)
        assert "contains_user_hogql" not in comment

    def test_execute_hogql_query_with_mcp_source_still_attributes_via_features(self):
        # Pulling MCP traffic apart by what it actually does is the whole point
        # of this fallback — confirm a $exception query from MCP attributes to
        # error_tracking, not the catch-all MCP product.
        marker = str(uuid.uuid4())
        reset_query_tags()
        tag_queries(kind="request", id="test", team_id=self.team.pk, source="mcp", feature="query")
        execute_hogql_query(
            f"SELECT count() FROM events WHERE distinct_id = '{marker}' AND event = '$exception'",  # noqa: S608
            team=self.team,
            query_type="HogQLQuery",
        )

        comment = self._get_log_comment(marker)

        assert comment["product"] == Product.ERROR_TRACKING.value


class TestAddFallbackQueryTags(BaseTest):
    def test_does_not_override_set_product(self):
        tags = QueryTags(product=Product.LOGS, feature=Feature.QUERY, scene="Cohort", query_type="TrendsQuery")
        add_fallback_query_tags(tags)
        assert tags.product == Product.LOGS
        assert tags.feature == Feature.QUERY

    def test_does_not_override_set_feature(self):
        tags = QueryTags(feature=Feature.DASHBOARD, scene="Cohort")
        add_fallback_query_tags(tags)
        assert tags.feature == Feature.DASHBOARD
        # product was unset, scene fills it in
        assert tags.product == Product.COHORTS

    def test_scene_fills_product_and_feature(self):
        tags = QueryTags(scene="SQLEditor")
        add_fallback_query_tags(tags)
        assert tags.product == Product.WAREHOUSE
        assert tags.feature == Feature.QUERY

    def test_kind_fills_product_only(self):
        # Not every query kind is customer-facing (e.g. VectorSearchQuery is internal Max AI).
        # Better to leave feature unset and let UntaggedQueryError surface where it matters.
        tags = QueryTags(query_type="TrendsQuery")
        add_fallback_query_tags(tags)
        assert tags.product == Product.PRODUCT_ANALYTICS
        assert tags.feature is None

    def test_mcp_source_fills_product_only(self):
        tags = QueryTags(source="mcp")
        add_fallback_query_tags(tags)
        assert tags.product == Product.MCP
        assert tags.feature is None

    def test_scene_takes_precedence_over_kind(self):
        # Scene maps to warehouse but kind would have mapped to product_analytics —
        # scene wins because it's checked first.
        tags = QueryTags(scene="SQLEditor", query_type="TrendsQuery")
        add_fallback_query_tags(tags)
        assert tags.product == Product.WAREHOUSE

    def test_kind_takes_precedence_over_mcp_source(self):
        tags = QueryTags(query_type="LogsQuery", source="mcp")
        add_fallback_query_tags(tags)
        assert tags.product == Product.LOGS

    def test_empty_tags_left_untouched(self):
        tags = QueryTags()
        add_fallback_query_tags(tags)
        assert tags.product is None
        assert tags.feature is None

    def test_unmapped_scene_falls_through(self):
        tags = QueryTags(scene="Unknown", query_type="TrendsQuery")
        add_fallback_query_tags(tags)
        assert tags.product == Product.PRODUCT_ANALYTICS

    @parameterized.expand([("Dashboard",), ("Dashboards",), ("Notebook",), ("Notebooks",), ("DebugQuery",), ("Max",)])
    def test_container_scene_defers_to_kind(self, scene):
        # Container scenes explicitly map to None — kind decides the product.
        tags = QueryTags(scene=scene, query_type="TrendsQuery")
        add_fallback_query_tags(tags)
        assert tags.product == Product.PRODUCT_ANALYTICS

    def test_unmapped_scene_and_kind_leaves_tags_untouched(self):
        tags = QueryTags(scene="Unknown", query_type="UnknownKind")
        add_fallback_query_tags(tags)
        assert tags.product is None
        assert tags.feature is None

    @parameterized.expand(
        [
            ("ai_generation", ["$ai_generation"], Product.LLM_ANALYTICS),
            ("ai_span", ["$ai_span"], Product.LLM_ANALYTICS),
            ("ai_trace", ["$ai_trace"], Product.LLM_ANALYTICS),
            ("ai_embedding", ["$ai_embedding"], Product.LLM_ANALYTICS),
            ("ai_metric", ["$ai_metric"], Product.LLM_ANALYTICS),
            ("ai_feedback", ["$ai_feedback"], Product.LLM_ANALYTICS),
            ("exception", ["$exception"], Product.ERROR_TRACKING),
            ("web_vitals", ["$web_vitals"], Product.WEB_ANALYTICS),
            ("feature_flag_called", ["$feature_flag_called"], Product.FEATURE_FLAGS),
        ]
    )
    def test_hogql_features_event_fills_product(self, _name, events, expected_product):
        tags = QueryTags(
            query_type="HogQLQuery",
            hogql_features=HogQLFeatures(tables=["events"], events=events),
        )
        add_fallback_query_tags(tags)
        assert tags.product == expected_product

    @parameterized.expand(
        [
            ("session_replay", ["session_replay_events"], Product.REPLAY),
            ("logs_table", ["logs"], Product.LOGS),
            ("events_table", ["events"], Product.PRODUCT_ANALYTICS),
        ]
    )
    def test_hogql_features_table_fills_product_when_no_event_match(self, _name, tables, expected_product):
        tags = QueryTags(
            query_type="HogQLQuery",
            hogql_features=HogQLFeatures(tables=tables, events=[]),
        )
        add_fallback_query_tags(tags)
        assert tags.product == expected_product

    def test_hogql_features_event_takes_precedence_over_table(self):
        # Querying the events table for $exception should attribute to error
        # tracking, not product analytics — events are more specific.
        tags = QueryTags(
            query_type="HogQLQuery",
            hogql_features=HogQLFeatures(tables=["events"], events=["$exception"]),
        )
        add_fallback_query_tags(tags)
        assert tags.product == Product.ERROR_TRACKING

    def test_hogql_features_only_apply_to_hogqlquery_kind(self):
        # A TrendsQuery would already be product_analytics via kind fallback;
        # we shouldn't let the AST features override that. More importantly,
        # the AST contents of e.g. an LLM-analytics insight (which uses
        # TrendsQuery on $ai_generation) shouldn't get re-attributed.
        tags = QueryTags(
            query_type="TrendsQuery",
            hogql_features=HogQLFeatures(tables=["events"], events=["$exception"]),
        )
        add_fallback_query_tags(tags)
        assert tags.product == Product.PRODUCT_ANALYTICS

    def test_hogql_features_does_not_override_set_product(self):
        tags = QueryTags(
            product=Product.MCP,
            query_type="HogQLQuery",
            hogql_features=HogQLFeatures(tables=["events"], events=["$exception"]),
        )
        add_fallback_query_tags(tags)
        assert tags.product == Product.MCP

    def test_hogql_features_take_precedence_over_mcp_source(self):
        # The whole point of the hogql_features fallback is to pull MCP traffic
        # apart by what it actually does — so even when source=mcp, a recognised
        # event filter must win over the catch-all MCP attribution.
        tags = QueryTags(
            query_type="HogQLQuery",
            source="mcp",
            hogql_features=HogQLFeatures(tables=["events"], events=["$exception"]),
        )
        add_fallback_query_tags(tags)
        assert tags.product == Product.ERROR_TRACKING

    def test_hogql_features_table_only_take_precedence_over_mcp_source(self):
        # Same precedence holds for the table-only path.
        tags = QueryTags(
            query_type="HogQLQuery",
            source="mcp",
            hogql_features=HogQLFeatures(tables=["session_replay_events"], events=[]),
        )
        add_fallback_query_tags(tags)
        assert tags.product == Product.REPLAY

    def test_hogql_features_unmapped_features_fall_through_to_mcp(self):
        # No interesting events, no recognised tables — let the MCP source
        # fallback fire instead.
        tags = QueryTags(
            query_type="HogQLQuery",
            source="mcp",
            hogql_features=HogQLFeatures(tables=[], events=[]),
        )
        add_fallback_query_tags(tags)
        assert tags.product == Product.MCP

    # --- query-structure fallback: wrapper / drill-down queries inherit the wrapped product ---

    @parameterized.expand(
        [("RetentionQuery",), ("TrendsQuery",), ("FunnelsQuery",), ("StickinessQuery",), ("LifecycleQuery",)]
    )
    def test_query_structure_resolves_actors_drilldowns(self, inner_kind):
        # "Open as new insight" from an actors modal posts a DataTableNode wrapping an
        # ActorsQuery → InsightActorsQuery → <insight>. Every outer kind maps to None, so the
        # product is inherited from the wrapped insight via the query-structure walk.
        query = {
            "kind": "DataTableNode",
            "source": {"kind": "ActorsQuery", "source": {"kind": "InsightActorsQuery", "source": {"kind": inner_kind}}},
        }
        tags = QueryTags(query_type="ActorsQuery", query=query)
        add_fallback_query_tags(tags)
        assert tags.product == Product.PRODUCT_ANALYTICS

    def test_query_structure_resolves_marketing_analytics_snakecase_query_type(self):
        # Marketing analytics runners pass a non-NodeKind query_type label ("marketing_analytics_table_query"),
        # so the query_type fallback can't map it — but tags.query carries the canonical kind.
        tags = QueryTags(
            query_type="marketing_analytics_table_query",
            query={"kind": "MarketingAnalyticsTableQuery"},
        )
        add_fallback_query_tags(tags)
        assert tags.product == Product.MARKETING_ANALYTICS

    def test_query_structure_does_not_override_set_product(self):
        query = {"kind": "ActorsQuery", "source": {"kind": "InsightActorsQuery", "source": {"kind": "RetentionQuery"}}}
        tags = QueryTags(product=Product.MCP, query_type="ActorsQuery", query=query)
        add_fallback_query_tags(tags)
        assert tags.product == Product.MCP

    def test_query_type_kind_takes_precedence_over_query_structure(self):
        # query_type maps directly (LogsQuery → logs); the structure walk must not override it.
        tags = QueryTags(query_type="LogsQuery", query={"kind": "TrendsQuery"})
        add_fallback_query_tags(tags)
        assert tags.product == Product.LOGS

    def test_query_structure_leaves_product_none_when_no_inner_kind_maps(self):
        # A bare ActorsQuery (raw persons drill-down) has no wrapped insight to inherit from.
        tags = QueryTags(query_type="ActorsQuery", query={"kind": "ActorsQuery", "source": None})
        add_fallback_query_tags(tags)
        assert tags.product is None

    def test_query_structure_accepts_pydantic_like_objects(self):
        # tags.query is usually the raw posted dict, but the walk also reads `.kind` / `.source` attributes.
        query = SimpleNamespace(
            kind="ActorsQuery",
            source=SimpleNamespace(
                kind="InsightActorsQuery", source=SimpleNamespace(kind="RetentionQuery", source=None)
            ),
        )
        tags = QueryTags(query_type="ActorsQuery", query=query)
        add_fallback_query_tags(tags)
        assert tags.product == Product.PRODUCT_ANALYTICS


@pytest.mark.parametrize(
    "access_method,expected",
    [
        # Programmatic key auth routes ClickHouse queries to the offline cluster as the API user
        # (see sync_execute); user-facing auth stays online.
        (AccessMethod.PERSONAL_API_KEY, True),
        (AccessMethod.PROJECT_SECRET_API_KEY, True),
        (AccessMethod.TEAM_SECRET_TOKEN, True),
        (AccessMethod.OAUTH, False),
        (AccessMethod.SHARING_TOKEN, False),
        (AccessMethod.ID_JAG, False),
        (None, False),
        ("", False),
    ],
)
def test_is_api_key_access_method(access_method, expected):
    assert is_api_key_access_method(access_method) is expected
