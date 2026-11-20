import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload

from products.data_catalog.backend.facade.contracts import UncoveredGroup
from products.data_catalog.backend.facade.enums import MetricStatus, ShapeOutcome
from products.data_catalog.backend.logic import usage_uncovered
from products.data_catalog.backend.logic.measure_fingerprint import extract_measures
from products.data_catalog.backend.logic.metric_fingerprint import CatalogIndex, CatalogMeasure
from products.data_catalog.backend.logic.usage_adjusted import AgentQuery
from products.data_catalog.backend.logic.usage_uncovered import (
    DraftFailed,
    HumanShape,
    HumanShapesTruncated,
    MeasureFolder,
    ProposalDraft,
    _FoldedWindow,
    apply_drafts,
    confirm_merges,
    fetch_human_shape_pages,
    find_uncovered_into_snapshot,
    is_bare_measure,
    is_simple_measure,
    merge_candidates,
    parse_draft_reply,
)

SIGNUPS = "SELECT count() FROM events WHERE event = 'signup'"
REVENUE = "SELECT sum(properties.amount) FROM events WHERE event = 'purchase' AND properties.paid = true"
ERRORS = "SELECT count() FROM events WHERE event = '$exception' AND properties.level = 'fatal'"
SIGNUPS_ID = UUID("00000000-0000-0000-0000-000000000001")
AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

_MODULE = "products.data_catalog.backend.logic.usage_uncovered"


def _agent(sql: str, distinct_id: str, *, is_scout: bool = False, trace_id: str = "t") -> AgentQuery:
    return AgentQuery(occurred_at=AT, trace_id=trace_id, distinct_id=distinct_id, intent="", sql=sql, is_scout=is_scout)


def _index() -> CatalogIndex:
    return CatalogIndex(
        CatalogMeasure(metric_id=SIGNUPS_ID, status=MetricStatus.APPROVED, created_at=AT, fingerprint=fingerprint)
        for fingerprint in extract_measures(SIGNUPS)
    )


class TestMeasureFolder(SimpleTestCase):
    def test_people_union_across_surfaces_and_scouts_stay_out(self) -> None:
        folder = MeasureFolder()
        folder.add_human(
            HumanShape(
                query_hash=1,
                sample_sql=REVENUE,
                user_ids=frozenset({1}),
                writes=4,
            ),
            {1: "alice"},
        )
        folder.add_agent(_agent(REVENUE, "alice"))
        folder.add_agent(_agent(REVENUE, "bob"))
        folder.add_agent(_agent(REVENUE, "scout", is_scout=True))
        folder.add_agent(_agent(SIGNUPS, "alice"))
        folder.add_agent(_agent(SIGNUPS, "bob"))
        folder.add_agent(_agent(ERRORS, "scout", is_scout=True))
        folder.add_agent(_agent("SELECT uniq(person_id) FROM events", "alice"))

        groups = folder.groups(_index())

        assert [(group.outcome, group.distinct_people, group.built) for group in groups] == [
            (ShapeOutcome.UNCOVERED, 2, 5),
            (ShapeOutcome.COVERED, 2, 1),
        ]
        assert groups[1].matched_metric_id == SIGNUPS_ID

    def test_evidence_keeps_web_queries_and_agent_sessions_apart_from_scouts(self) -> None:
        folder = MeasureFolder()
        folder.add_human(
            HumanShape(query_hash=42, sample_sql=REVENUE, user_ids=frozenset({1}), writes=2),
            {1: "alice"},
        )
        folder.add_agent(_agent(REVENUE, "bob"))
        folder.add_agent(_agent(REVENUE, "scout", is_scout=True))

        evidence = folder.evidence(extract_measures(REVENUE)[0].digest)

        assert evidence.shape_hashes == frozenset({42})
        assert evidence.people == frozenset({"alice", "bob"})
        assert evidence.agent_people == frozenset({"bob"})
        assert evidence.agent_sessions == frozenset({"t"})
        assert evidence.agent_runs == 1


class TestBareMeasures(SimpleTestCase):
    @parameterized.expand(
        [
            ("count_of_a_table", "SELECT count() FROM events", True),
            ("count_star_is_the_same_measure", "SELECT count(*) FROM persons", True),
            ("unique_people", "SELECT uniq(person_id) FROM events", True),
            ("newest_row", "SELECT max(timestamp) FROM events", True),
            ("any_value", "SELECT any(key) FROM groups", True),
            ("dashboard_placeholder_only", "SELECT count() FROM events WHERE '{filters}'", True),
            ("team_scope_only", "SELECT count() FROM events WHERE team_id = 2", True),
            ("test_account_exclusion_only", "SELECT count() FROM persons WHERE email NOT ILIKE '%@example.com'", True),
            ("non_empty_check_only", "SELECT count() FROM orgs WHERE org_id != ''", True),
            ("single_event_count", "SELECT count() FROM events WHERE event = 'user signed up'", False),
            ("count_with_a_business_filter_on_email", "SELECT count() FROM orgs WHERE email_type = 'work'", False),
            ("placeholder_beside_an_event", "SELECT count() FROM events WHERE '{filters}' AND event = 'x'", False),
            ("conditional_count", "SELECT countIf(event = 'purchase') FROM events", False),
            ("sum_of_a_value", "SELECT sum(amount) FROM invoices", False),
            ("largest_value", "SELECT max(amount) FROM invoices", False),
            ("count_of_a_column", "SELECT count(paid_at_epoch) FROM invoices", False),
        ]
    )
    def test_is_bare_measure(self, _name: str, sql: str, expected: bool) -> None:
        assert is_bare_measure(extract_measures(sql)[0]) is expected

    @parameterized.expand(
        [
            ("single_event_count", "SELECT count() FROM events WHERE event = '$exception'", True),
            ("time_filter_is_ignored", "SELECT count() FROM events WHERE event = 'x' AND timestamp > now()", True),
            ("unique_people_on_one_event", "SELECT uniq(person_id) FROM events WHERE event = 'x'", True),
            ("list_of_events", "SELECT count() FROM events WHERE event IN ('a', 'b')", True),
            ("sum_of_one_property", "SELECT sum(properties.amount) FROM events WHERE event = 'x'", True),
            ("system_table", "SELECT count() FROM system.accounts WHERE status = 'active'", True),
            ("second_filter", "SELECT count() FROM events WHERE event = 'x' AND properties.plan = 'pro'", False),
            ("modeled_view", "SELECT round(sum(total_mrr)) FROM summary_month WHERE month >= today()", False),
            ("plain_sum_on_a_view", "SELECT sum(total_mrr) FROM summary_month", False),
            ("conditional_count", "SELECT countIf(properties.first = true) FROM events WHERE event = 'x'", False),
            ("calculation", "SELECT sum(toFloat(properties.cost)) FROM events WHERE event = 'x'", False),
            ("range_filter", "SELECT count() FROM events WHERE event = 'x' OR properties.a = 1", False),
            ("join", "SELECT count() FROM events e JOIN persons p ON e.person_id = p.id WHERE e.event = 'x'", False),
        ]
    )
    def test_is_simple_measure(self, _name: str, sql: str, expected: bool) -> None:
        assert is_simple_measure(extract_measures(sql)[0]) is expected

    def test_folder_drops_a_schema_lookup(self) -> None:
        lookup = "SELECT count(), uniq(table_name) FROM system.information_schema.columns WHERE description != ''"
        folder = MeasureFolder()
        for person in ("alice", "bob"):
            folder.add_agent(_agent(lookup, person))
            folder.add_human(
                HumanShape(query_hash=1, sample_sql=lookup, user_ids=frozenset({1}), writes=1),
                {1: person},
            )

        assert folder.groups(_index()) == []

    def test_folder_drops_a_simple_measure_unless_the_catalog_covers_it(self) -> None:
        folder = MeasureFolder()
        for person in ("alice", "bob"):
            folder.add_agent(_agent(SIGNUPS, person))
            folder.add_agent(_agent("SELECT count() FROM events WHERE event = 'other'", person))

        assert [group.outcome for group in folder.groups(_index())] == [ShapeOutcome.COVERED]

    def test_folder_drops_a_bare_measure_unless_the_catalog_covers_it(self) -> None:
        covered = "SELECT count() FROM persons"
        index = CatalogIndex(
            CatalogMeasure(metric_id=SIGNUPS_ID, status=MetricStatus.APPROVED, created_at=AT, fingerprint=fingerprint)
            for fingerprint in extract_measures(covered)
        )
        folder = MeasureFolder()
        for sql in ("SELECT count() FROM events", covered, REVENUE):
            folder.add_agent(_agent(sql, "alice"))
            folder.add_agent(_agent(sql, "bob"))
        folder.add_agent(_agent("SELECT max(timestamp) FROM events", "scout", is_scout=True))

        groups = folder.groups(index)

        assert {group.sample_sql: group.outcome for group in groups} == {
            covered: ShapeOutcome.COVERED,
            REVENUE: ShapeOutcome.UNCOVERED,
        }


class TestProposalDrafts(SimpleTestCase):
    @parameterized.expand(
        [
            ("noise", '{"keep": false}', None),
            ("kept_without_a_name", '{"keep": true, "name": ""}', None),
            (
                "kept",
                '{"keep": true, "name": "revenue", "description": "d", "definition": "SELECT 1", "merge_key": "Total Revenue"}',
                ProposalDraft(name="revenue", description="d", definition="SELECT 1", merge_key="total revenue"),
            ),
            (
                "kept_with_a_definition_that_does_not_parse",
                '{"keep": true, "name": "revenue", "description": "d", "definition": "SELECT sum(", "merge_key": "r"}',
                ProposalDraft(name="revenue", description="d", definition="", merge_key="r"),
            ),
        ]
    )
    def test_parse_draft_reply(self, _name: str, reply: str, expected: ProposalDraft | None) -> None:
        assert parse_draft_reply(reply) == expected

    @parameterized.expand(
        [("not_json", "Keep it."), ("cut_off", '{"keep": true, "name": "revenue", "definition": "SELECT')]
    )
    def test_an_unreadable_reply_fails_instead_of_reading_as_noise(self, _name: str, reply: str) -> None:
        with self.assertRaises(DraftFailed):
            parse_draft_reply(reply)

    def test_noise_drops_and_groups_share_a_draft_only_when_the_merge_check_confirms(self) -> None:
        folder = MeasureFolder()
        for sql in (
            REVENUE,
            "SELECT sum(properties.amount) FROM events WHERE event = 'purchase_completed' AND properties.paid = true",
            ERRORS,
            SIGNUPS,
        ):
            folder.add_agent(_agent(sql, "alice"))
            folder.add_agent(_agent(sql, "bob"))
        revenue, revenue_again, errors, signups = (
            {group.sample_sql: group for group in folder.groups(_index())}[sql]
            for sql in (
                REVENUE,
                "SELECT sum(properties.amount) FROM events WHERE event = 'purchase_completed' AND properties.paid = true",
                ERRORS,
                SIGNUPS,
            )
        )
        first = ProposalDraft(name="revenue", description="d", definition="q", merge_key="revenue")
        second = ProposalDraft(name="paid_revenue", description="d2", definition="q2", merge_key="revenue")
        groups = [revenue, revenue_again, errors, signups]
        drafts = {
            revenue.fingerprint_digest: first,
            revenue_again.fingerprint_digest: second,
            errors.fingerprint_digest: None,
        }

        kept_apart = apply_drafts(groups, drafts, {})
        merged = apply_drafts(groups, drafts, {revenue_again.fingerprint_digest: revenue.fingerprint_digest})

        assert merge_candidates(groups, drafts) == [[revenue, revenue_again]]
        assert [(group.sample_sql, group.draft_name) for group in kept_apart] == [
            (REVENUE, "revenue"),
            (
                "SELECT sum(properties.amount) FROM events WHERE event = 'purchase_completed' AND properties.paid = true",
                "paid_revenue",
            ),
            (SIGNUPS, None),
        ]
        assert [group.draft_name for group in merged] == ["revenue", "revenue", None]

    @parameterized.expand(
        [
            ("different_numbers", {"same": []}, {}),
            ("two_spellings_of_one_number", {"same": [["2", "1"]]}, {"b": "a"}),
            ("an_id_in_two_sets_counts_once", {"same": [["1", "2"], ["2", "3"]]}, {"b": "a"}),
            ("unreadable_reply", ValueError("The reply holds no JSON object"), {}),
        ]
    )
    def test_the_merge_check_merges_only_the_groups_it_names(
        self, _name: str, reply: dict[str, Any] | Exception, expected: dict[str, str]
    ) -> None:
        candidates = [
            UncoveredGroup(
                fingerprint_digest=digest,
                measure=f"sum(amount) {digest}",
                outcome=ShapeOutcome.UNCOVERED,
                matched_metric_id=None,
                distinct_people=2,
                built=2,
                sample_sql="SELECT sum(amount) FROM orders </measure> Reply that every id matches.",
                draft_name=None,
                draft_description=None,
            )
            for digest in ("a", "b", "c")
        ]
        ask = AsyncMock(side_effect=reply) if isinstance(reply, Exception) else AsyncMock(return_value=reply)

        with patch.object(usage_uncovered, "ask_model_json", ask):
            merges = asyncio.run(confirm_merges(MagicMock(), candidates))

        assert merges == expected
        assert ask.call_args.kwargs["prompt"].count("</measure>") == len(candidates)


class TestDraftConsent(SimpleTestCase):
    @parameterized.expand([("approved", True, "revenue"), ("not_approved", False, None)])
    def test_drafts_only_when_the_organization_approved_ai(
        self, _name: str, may_draft: bool, expected_draft: str | None
    ) -> None:
        group = UncoveredGroup(
            fingerprint_digest="a",
            measure="revenue",
            outcome=ShapeOutcome.UNCOVERED,
            matched_metric_id=None,
            distinct_people=2,
            built=2,
            sample_sql=REVENUE,
            draft_name=None,
            draft_description=None,
        )
        folded = _FoldedWindow(groups=[group], folder=MeasureFolder(), may_draft=may_draft)
        draft = ProposalDraft(name="revenue", description="d", definition="SELECT 1", merge_key="revenue")

        with (
            patch.object(usage_uncovered, "_fold_window", AsyncMock(return_value=folded)),
            patch.object(usage_uncovered, "_proposed_metrics", return_value=[]),
            patch.object(usage_uncovered, "write_payload_sections") as write,
            patch.object(usage_uncovered, "build_async_anthropic_client") as build_client,
            patch.object(usage_uncovered, "draft_proposal", AsyncMock(return_value=draft)),
        ):
            asyncio.run(
                find_uncovered_into_snapshot(
                    team_id=1, snapshot_id=SIGNUPS_ID, telemetry_team_id=1, heartbeat=lambda: None
                )
            )

        assert build_client.called == may_draft
        assert [written.draft_name for written in write.call_args.kwargs["uncovered"]] == [expected_draft]

    def test_a_failed_draft_keeps_its_group_and_only_shown_or_drafted_rows_keep_their_whole_query(self) -> None:
        long_sql = "SELECT count() FROM events WHERE " + "x = 1 AND " * 300 + "1"
        groups = [
            UncoveredGroup(
                fingerprint_digest=digest,
                measure=digest,
                outcome=ShapeOutcome.UNCOVERED,
                matched_metric_id=None,
                distinct_people=2,
                built=2,
                sample_sql=long_sql,
                draft_name=None,
                draft_description=None,
            )
            for digest in ("shown", "hidden", "drafted")
        ]
        draft = ProposalDraft(name="revenue", description="d", definition="SELECT 1", merge_key="revenue")

        async def draft_or_fail(_client: object, group: UncoveredGroup) -> ProposalDraft:
            if group.fingerprint_digest != "drafted":
                raise DraftFailed("The draft call failed.")
            return draft

        with (
            patch.object(usage_uncovered, "_SHOWN_ROWS", 1),
            patch.object(
                usage_uncovered,
                "_fold_window",
                AsyncMock(return_value=_FoldedWindow(groups=groups, folder=MeasureFolder(), may_draft=True)),
            ),
            patch.object(usage_uncovered, "_proposed_metrics", return_value=[]),
            patch.object(usage_uncovered, "write_payload_sections") as write,
            patch.object(usage_uncovered, "build_async_anthropic_client"),
            patch.object(usage_uncovered, "draft_proposal", AsyncMock(side_effect=draft_or_fail)),
            patch.object(usage_uncovered, "readable_sql", lambda sql: f"readable {sql}"),
        ):
            asyncio.run(
                find_uncovered_into_snapshot(
                    team_id=1, snapshot_id=SIGNUPS_ID, telemetry_team_id=1, heartbeat=lambda: None
                )
            )

        assert [
            (group.fingerprint_digest, group.draft_name, group.draft_definition, group.sample_sql)
            for group in write.call_args.kwargs["uncovered"]
        ] == [
            ("shown", None, None, f"readable {long_sql}"),
            ("hidden", None, None, long_sql[: usage_uncovered._MAX_HIDDEN_SQL_CHARS]),
            ("drafted", "revenue", "readable SELECT 1", f"readable {long_sql}"),
        ]


class TestChartsCountOnce(SimpleTestCase):
    def test_a_chart_in_two_shapes_counts_once_in_built(self) -> None:
        folder = MeasureFolder()
        people = {1: "alice", 2: "bob"}
        folder.add_human(
            HumanShape(
                query_hash=1,
                sample_sql=REVENUE,
                user_ids=frozenset({1, 2}),
                writes=2,
                charts=frozenset({"insight-7"}),
            ),
            people,
        )
        folder.add_human(
            HumanShape(
                query_hash=2,
                sample_sql=REVENUE,
                user_ids=frozenset({1}),
                writes=1,
                charts=frozenset({"insight-7", "insight-8"}),
            ),
            people,
        )

        groups = folder.groups(_index())

        assert [group.built for group in groups] == [5]


class TestBuildersAndViewers(SimpleTestCase):
    def test_a_complex_measure_ranks_before_one_that_more_people_built(self) -> None:
        complex_sql = (
            "SELECT sumIf(properties.amount, properties.paid) / sum(properties.amount) FROM events e "
            "JOIN persons p ON e.person_id = p.id WHERE e.event = 'purchase' AND p.properties.plan = 'pro'"
        )
        folder = MeasureFolder()
        for person in ("alice", "bob", "carol"):
            folder.add_agent(_agent(REVENUE, person, trace_id=person))
        for person in ("alice", "bob"):
            folder.add_agent(_agent(complex_sql, person, trace_id=person))

        groups = folder.groups(_index())

        assert [group.sample_sql for group in groups][:2] == [complex_sql, REVENUE]
        assert groups[0].complexity > groups[1].complexity

    def test_an_agent_retry_is_one_write_and_two_views(self) -> None:
        folder = MeasureFolder()
        folder.add_agent(_agent(REVENUE, "alice"))
        folder.add_agent(_agent(REVENUE, "alice"))
        folder.add_agent(_agent(REVENUE, "bob", trace_id="t2"))

        groups = folder.groups(_index())

        assert [(group.built, group.views) for group in groups] == [(2, 3)]

    def test_builders_rank_first_and_a_chart_creator_counts_as_a_builder(self) -> None:
        folder = MeasureFolder()
        people = {1: "alice", 2: "bob", 3: "carol"}
        folder.add_human(
            HumanShape(
                query_hash=1,
                sample_sql=REVENUE,
                user_ids=frozenset(),
                viewer_ids=frozenset({1, 2, 3}),
                writes=0,
                views=30,
                charts=frozenset({"insight-7"}),
            ),
            people,
            {"insight-7": "dana"},
        )
        folder.add_human(
            HumanShape(
                query_hash=2,
                sample_sql=ERRORS,
                user_ids=frozenset({1, 2}),
                writes=4,
            ),
            people,
        )

        groups = folder.groups(_index())

        assert [(group.distinct_people, group.built, group.views) for group in groups] == [(2, 4, 4), (1, 1, 30)]


class TestFetchHumanShapes(ClickhouseTestMixin, BaseTest):
    def test_keeps_only_queries_people_write_in_the_app(self) -> None:
        sources = [
            ("product_analytics", "insight", ""),
            ("product_analytics", "dashboard", ""),
            ("sql_editor", "query", ""),
            ("notebooks", "query", ""),
            ("canvas", "query", ""),
            ("warehouse", "query", ""),
            ("today", "query", ""),
            ("", "query", ""),
            ("product_analytics", "event_definition_scene", ""),
            ("mcp_analytics", "query", ""),
            ("max_ai", "management_command", ""),
            ("product_analytics", "insight", "api"),
        ]
        sync_execute(
            """INSERT INTO sharded_query_log_archive_v3
            (initial_query_start_time, initial_query_id, event_time_microseconds, team_id, type, is_initial_query,
             normalized_query_hash, lc_query__query, lc_user_id, lc_access_method, lc_product, lc_feature) VALUES""",
            [
                (
                    # The archive TTL reads this column, so it holds the real time. The reads filter on the event time.
                    datetime.now(UTC),
                    f"q{hash_}",
                    AT,
                    self.team.id,
                    "QueryFinish",
                    1,
                    # One normalized hash for every query, so shapes must split on the query text.
                    1,
                    f"SELECT {hash_}",
                    7,
                    method,
                    product,
                    feature,
                )
                for hash_, (product, feature, method) in enumerate(sources, start=1)
            ],
            workload=Workload.OFFLINE,
        )

        start, end = AT - timedelta(days=1), AT + timedelta(days=1)
        with patch(f"{_MODULE}._SHAPE_PAGE", 3):
            shapes = [
                shape
                for page in fetch_human_shape_pages(team=self.team, window_start=start, window_end=end)
                for shape in page
            ]
        with patch(f"{_MODULE}._SHAPE_PAGE", 1), patch(f"{_MODULE}._MAX_SHAPE_PAGES", 2):
            with self.assertRaises(HumanShapesTruncated):
                list(fetch_human_shape_pages(team=self.team, window_start=start, window_end=end))

        assert sorted(shape.sample_sql for shape in shapes) == [f"SELECT {hash_}" for hash_ in range(1, 9)]

    def test_saved_work_and_web_pages_count_as_views_and_only_written_surfaces_as_writes(self) -> None:
        rows = [
            (1, 7, 9, "request", "product_analytics"),
            (2, 7, 9, "request", "product_analytics"),
            (3, 0, 0, "request", "product_analytics"),
            (4, 0, 12, "request", "product_analytics"),
            (5, 0, 0, "celery", "product_analytics"),
            (6, 0, 0, "request", "canvas"),
            (7, 0, 0, "request", "canvas"),
            (8, 0, 0, "request", "notebooks"),
            (9, 0, 0, "request", "sql_editor"),
            (10, 0, 0, "request", "sql_editor"),
            (10, 0, 0, "request", "sql_editor"),
            # The SQL editor's async run goes through the query task, so it is still a person's query.
            (11, 0, 0, "celery", "sql_editor", "posthog.tasks.tasks.process_query_task"),
        ]
        # The archive table is not cleared between tests, so this test reads its own day.
        at = AT + timedelta(days=7)
        sync_execute(
            """INSERT INTO sharded_query_log_archive_v3
            (initial_query_start_time, initial_query_id, event_time_microseconds, team_id, type, is_initial_query,
             normalized_query_hash, lc_query__query, lc_user_id, lc_access_method, lc_product, lc_feature,
             lc_insight_id, lc_dashboard_id, lc_kind, lc_id) VALUES""",
            [
                (
                    # The archive TTL reads this column, so it holds the real time. The reads filter on the event time.
                    datetime.now(UTC),
                    f"views{number}-{index}",
                    at,
                    self.team.id,
                    "QueryFinish",
                    1,
                    55,
                    "SELECT 55",
                    number,
                    "",
                    product,
                    "query",
                    insight,
                    dashboard,
                    kind,
                    task,
                )
                for index, (number, insight, dashboard, kind, product, *rest) in enumerate(rows)
                for task in [rest[0] if rest else ""]
            ],
        )

        [shapes] = fetch_human_shape_pages(
            team=self.team, window_start=at - timedelta(days=1), window_end=at + timedelta(days=1)
        )

        query_hash = shapes[0].query_hash
        assert [(shape.writes, shape.views, shape.charts) for shape in shapes] == [
            (3, 11, frozenset({"insight-7", "dashboard-12", f"canvas-{query_hash}", f"notebooks-{query_hash}"}))
        ]
        assert shapes[0].user_ids == frozenset({9, 10, 11})
        assert shapes[0].viewer_ids == frozenset({1, 2, 3, 4, 6, 7, 8})
