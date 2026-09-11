import json
from typing import Any

from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    BaseMathType,
    DateRange,
    EventsNode,
    FunnelMathType,
    FunnelsQuery,
    HogQLFilters,
    HogQLQuery,
    QueryScanMode,
    RetentionFilter,
    RetentionQuery,
    RetentionType,
    TrendsQuery,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query_stats import QueryStats, RecordedExecution

from posthog.clickhouse.query_tagging import AccessMethod, Feature, reset_query_tags, tag_queries
from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.slot import slot_key
from posthog.query_scan.trigger import MAX_EXECUTION_BYTES, _open_filters_placeholder, maybe_trigger_query_scan

FLAG = QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=0.5)

# A query with one `IN` subquery, so the stub collects exactly one subquery to print.
_QUERY_WITH_SUBQUERY = "select 1 from events where event in (select 'x')"


def _execution(
    sql: str = _QUERY_WITH_SUBQUERY, rows_read: int = 100, values: dict[str, Any] | None = None
) -> RecordedExecution:
    return RecordedExecution(
        tree=parse_select(sql), context=HogQLContext(team_id=1, values=values or {}), rows_read=rows_read
    )


def _stats(*, duration_ms: float = 2000.0, executions: list[RecordedExecution] | None = None) -> QueryStats:
    stats = QueryStats(rows_read=10, duration_ms=duration_ms)
    stats.executions.extend(executions if executions is not None else [_execution()])
    return stats


def _tag_as_api_key(test: "TestQueryScanTrigger") -> None:
    tag_queries(access_method=AccessMethod.PERSONAL_API_KEY)


def _store_a_slot(test: "TestQueryScanTrigger") -> None:
    test.redis.get.return_value = json.dumps({"version": 1, "status": "done", "findings": []})


def _spend_the_enqueue_budget(test: "TestQueryScanTrigger") -> None:
    test.redis.incr.return_value = 11


def _lose_the_slot_claim(test: "TestQueryScanTrigger") -> None:
    test.redis.set.return_value = None


class TestQueryScanTrigger(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.redis = mock.Mock()
        self.redis.get.return_value = None
        self.redis.incr.return_value = 1
        patcher = mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        delay_patcher = mock.patch("posthog.tasks.query_scan.analyze_query_scan.delay")
        self.delay = delay_patcher.start()
        self.addCleanup(delay_patcher.stop)
        # The prepared tree is not printable in a unit test, so control the printed SQL directly.
        print_patcher = mock.patch("posthog.query_scan.trigger.print_prepared_ast", return_value="SELECT 1")
        self.print = print_patcher.start()
        self.addCleanup(print_patcher.stop)
        self.addCleanup(reset_query_tags)

    def _assert_no_slot_was_claimed(self) -> None:
        key = slot_key(1, "cache_key_1", FLAG.thresholds_fingerprint)
        slot_writes = [call for call in self.redis.set.call_args_list if call.args[0] == key]
        assert slot_writes == []

    def _trigger(self, **overrides: Any):
        arguments: dict[str, Any] = {
            "flag": FLAG,
            "stats": _stats(),
            "team_id": 1,
            "cache_key": "cache_key_1",
            "query": HogQLQuery(query="select 1"),
            "trigger": "fresh",
            "cacheable": True,
            "insight_id": 7,
            "dashboard_id": 3,
        }
        return maybe_trigger_query_scan(**{**arguments, **overrides})

    @parameterized.expand(
        [
            ("flag off", {"flag": None}, None, "flag_off"),
            ("below the floor", {"stats": _stats(duration_ms=999.0)}, None, "below_floor"),
            ("api key run", {}, _tag_as_api_key, "api_key"),
            (
                "direct connection",
                {"query": HogQLQuery(query="select 1", connectionId="connection_1")},
                None,
                "direct_connection",
            ),
            ("result not cacheable", {"cacheable": False}, None, "not_cacheable"),
            ("slot already exists", {}, _store_a_slot, "slot_exists"),
            ("over the enqueues a team gets in a minute", {}, _spend_the_enqueue_budget, "rate_limited"),
        ]
    )
    def test_skips_with_a_reason(self, _name, overrides, prepare, expected_reason) -> None:
        if prepare is not None:
            prepare(self)

        result = self._trigger(**overrides)

        assert result == expected_reason
        self.delay.assert_not_called()
        self._assert_no_slot_was_claimed()

    def test_a_killed_run_is_analyzed_below_the_floor(self) -> None:
        # A memory-limit kill can die in under a second, and nobody gets a result from it, so the
        # floor must not keep it from the one analysis that can ever advise the person.
        result = self._trigger(
            stats=_stats(duration_ms=999.0), killed=True, error_type="ClickHouseQueryMemoryLimitExceeded"
        )

        assert result is None
        assert self.delay.call_args.kwargs["killed"] is True
        assert self.delay.call_args.kwargs["duration_ms"] == 999

    def test_an_mcp_run_is_analyzed_despite_its_api_key(self) -> None:
        tag_queries(access_method=AccessMethod.PERSONAL_API_KEY, feature=Feature.MCP)

        result = self._trigger()

        assert result is None
        assert self.delay.call_count == 1

    def test_a_lost_slot_claim_does_not_enqueue_a_second_job(self) -> None:
        # Two slow runs of the same query can both find no slot, so the conditional write is what
        # keeps one job per slot; without it the loser would enqueue a duplicate analysis.
        _lose_the_slot_claim(self)

        result = self._trigger()

        assert result == "slot_exists"
        self.delay.assert_not_called()

    def test_a_threshold_change_reanalyzes_under_the_new_key(self) -> None:
        # A done slot from other thresholds sits under its own key, so a run under the current
        # thresholds still claims a fresh slot and enqueues, instead of reading the old slot as in
        # place and never analyzing until it expires.
        other = QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.2, persons_ratio=0.5)
        other_key = slot_key(1, "cache_key_1", other.thresholds_fingerprint)
        new_key = slot_key(1, "cache_key_1", FLAG.thresholds_fingerprint)
        stored = {other_key: json.dumps({"version": 1, "status": "done", "findings": []})}
        self.redis.get.side_effect = lambda key: stored.get(key)

        def claim(key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool | None:
            if nx and key in stored:
                return None
            stored[key] = value
            return True

        self.redis.set.side_effect = claim

        result = self._trigger()

        assert result is None
        assert self.delay.call_count == 1
        assert new_key in stored
        assert json.loads(stored[new_key])["status"] == "pending"

    def test_a_broker_failure_does_not_fail_the_query(self) -> None:
        # ClickHouse has already done the work and the result is not cached yet, so an optional
        # side effect must not take a successful query down with it.
        self.delay.side_effect = Exception("broker unavailable")

        result = self._trigger()

        assert result == "enqueue_failed"
        self.redis.delete.assert_called_once_with(slot_key(1, "cache_key_1", FLAG.thresholds_fingerprint))

    def test_the_payload_carries_the_event_filter_classification(self) -> None:
        # The job folds this verdict into the plan, so a payload that stopped carrying it would
        # drop the tree's reason for why the filter could not prune.
        result = self._trigger()

        assert result is None
        enqueued = self.delay.call_args.kwargs["executions"]
        assert enqueued[0]["event_filter"] == {"classification": "usable", "reason": None}

    def test_a_killed_run_records_that_on_the_pending_slot(self) -> None:
        # The scan endpoint answers from this slot until the job finishes, so a stopped run that
        # left no `killed` here would be reported as one that ran to completion.
        self._trigger(killed=True, error_type="ClickHouseQueryTimeOut")

        _key, payload = self.redis.set.call_args.args
        assert json.loads(payload)["killed"] is True
        # The job groups the analytics event by the error kind, so it travels on the payload.
        assert self.delay.call_args.kwargs["error_type"] == "ClickHouseQueryTimeOut"

    def test_an_oversized_selected_execution_aborts_the_whole_scan(self) -> None:
        # A person reads the advice as if it covered the whole run, so a run with a selected
        # execution too large to ship is not analyzed in part. The claimed slot is dropped, so a
        # later run can try again.
        heavy = _execution(rows_read=100)
        # The values count because one large literal can outweigh the SQL around it.
        oversized = _execution(rows_read=50, values={"hogql_val_0": "x" * (MAX_EXECUTION_BYTES + 1)})

        result = self._trigger(stats=_stats(executions=[heavy, oversized]))

        assert result == "too_large"
        self.delay.assert_not_called()
        self.redis.delete.assert_called_once_with(slot_key(1, "cache_key_1", FLAG.thresholds_fingerprint))

    def test_ships_several_printable_executions_heaviest_first(self) -> None:
        # An insight fans out into several executions; the job explains the heaviest, so the payload
        # carries them ordered by rows read.
        light = _execution(rows_read=50)
        heavy = _execution(rows_read=100)

        result = self._trigger(stats=_stats(executions=[light, heavy]))

        assert result is None
        enqueued = self.delay.call_args.kwargs["executions"]
        assert [execution["rows_read"] for execution in enqueued] == [100, 50]
        assert enqueued[0]["stubbed_sql"] == "SELECT 1"
        assert enqueued[0]["subqueries"] == ["SELECT 1"]

    @parameterized.expand(
        [
            ("hogql", HogQLQuery(query="select 1"), "HogQLQuery"),
            ("trends", TrendsQuery(series=[EventsNode(event="$pageview")]), "TrendsQuery"),
            ("funnels", FunnelsQuery(series=[EventsNode(event="a"), EventsNode(event="b")]), "FunnelsQuery"),
        ]
    )
    def test_enqueues_the_run_and_writes_a_pending_slot(self, _name, query, expected_kind) -> None:
        result = self._trigger(query=query)

        assert result is None
        assert self.delay.call_count == 1
        enqueued = self.delay.call_args.kwargs
        assert enqueued["cache_key"] == "cache_key_1"
        assert enqueued["rows_read"] == 10
        assert enqueued["duration_ms"] == 2000
        assert enqueued["trigger"] == "fresh"
        assert enqueued["query_kind"] == expected_kind
        assert (enqueued["insight_id"], enqueued["dashboard_id"]) == (7, 3)
        assert len(enqueued["executions"]) == 1

        key, payload = self.redis.set.call_args.args
        assert key == slot_key(1, "cache_key_1", FLAG.thresholds_fingerprint)
        assert json.loads(payload)["status"] == "pending"
        assert self.redis.set.call_args.kwargs == {"ex": 600, "nx": True}
        # A count left without a TTL would stand forever and cap the team for good.
        self.redis.set.assert_any_call("query_scan:enqueues:1", 0, nx=True, ex=60)

    def test_the_payload_says_whether_all_time_was_chosen(self) -> None:
        self._trigger(query=TrendsQuery(series=[EventsNode(event="$pageview")], dateRange=DateRange(date_from="all")))

        assert self.delay.call_args.kwargs["all_time"] is True

    @parameterized.expand(
        [
            (
                "first time for user math",
                TrendsQuery(series=[EventsNode(event="$pageview", math=BaseMathType.FIRST_TIME_FOR_USER)]),
                True,
            ),
            (
                "a first-time funnel step",
                FunnelsQuery(
                    series=[EventsNode(event="a", math=FunnelMathType.FIRST_TIME_FOR_USER), EventsNode(event="b")]
                ),
                True,
            ),
            (
                "first-time retention",
                RetentionQuery(retentionFilter=RetentionFilter(retentionType=RetentionType.RETENTION_FIRST_TIME)),
                True,
            ),
            ("plain trends", TrendsQuery(series=[EventsNode(event="$pageview")]), False),
            ("raw sql", HogQLQuery(query="select 1"), False),
        ]
    )
    def test_the_payload_says_whether_the_insight_reads_all_history_by_design(self, _name, query, expected) -> None:
        # Such an insight has to start at the project's first event whatever its date range, so the
        # job must not advise a start date it cannot use.
        self._trigger(query=query)

        assert self.delay.call_args.kwargs["all_history_by_design"] is expected


class TestOpenFiltersPlaceholder(SimpleTestCase):
    @parameterized.expand(
        [
            ("no placeholder at all", HogQLQuery(query="select count() from events"), False),
            ("open filters", HogQLQuery(query="select count() from events where {filters}"), True),
            (
                "filters with a start date",
                HogQLQuery(
                    query="select count() from events where {filters}",
                    filters=HogQLFilters(dateRange=DateRange(date_from="-7d")),
                ),
                False,
            ),
            (
                "filters set to all time",
                HogQLQuery(
                    query="select count() from events where {filters}",
                    filters=HogQLFilters(dateRange=DateRange(date_from="all")),
                ),
                True,
            ),
            # An end date on its own leaves the start of the range open.
            (
                "filters with only an end date",
                HogQLQuery(
                    query="select count() from events where {filters}",
                    filters=HogQLFilters(dateRange=DateRange(date_to="-1d")),
                ),
                True,
            ),
            (
                "only a dotted call placeholder",
                HogQLQuery(
                    query="select toStartOfInterval(timestamp, {filters.interval('day')}), count() from events group by 1"
                ),
                False,
            ),
            ("an insight built from pickers", TrendsQuery(series=[EventsNode(event="$pageview")]), False),
        ]
    )
    def test_only_a_date_carrying_placeholder_puts_the_start_date_on_the_insight(
        self, _name: str, query: HogQLQuery | TrendsQuery, expected: bool
    ) -> None:
        assert _open_filters_placeholder(query) is expected
