import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest import mock

from parameterized import parameterized

from posthog.hogql import query_stats
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast

from posthog.clickhouse.workload import Workload
from posthog.errors import InternalCHQueryError
from posthog.query_scan import slot
from posthog.query_scan.flag import QueryScanFlag, QueryScanMode
from posthog.query_scan.job import Execution, InlineOutcome, QueryScanJob, run_query_scan, run_query_scan_inline
from posthog.query_scan.stub import stub_in_subqueries

from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

FIXTURES = Path(__file__).parent / "fixtures"
FLAG = QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=0.5)

_OTHER_ERROR = InternalCHQueryError("Estimated execution time too long", code=160)

# The `system.parts` metadata query returns average rows per granule per table.
_ROW_AVERAGES = [
    ["sharded_events", 740.0],
    ["person", 3955.0],
    ["person_distinct_id2", 512.0],
    ["person_distinct_id_overrides", 512.0],
]


def _plan(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text()


def _fake_job_boundaries(test: BaseTest, stored: dict[str, Any], flag: QueryScanFlag = FLAG) -> mock.Mock:
    redis = mock.Mock()
    redis.get.side_effect = lambda key: stored.get(key)
    redis.set.side_effect = lambda key, value, ex=None, nx=False: stored.__setitem__(key, value)
    redis.delete.side_effect = lambda key: stored.pop(key, None)
    redis_patcher = mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=redis)
    flag_patcher = mock.patch("posthog.query_scan.job.get_query_scan_flag", return_value=flag)
    capture_patcher = mock.patch("posthog.query_scan.job.ph_scoped_capture")
    for patcher in (redis_patcher, flag_patcher):
        patcher.start()
        test.addCleanup(patcher.stop)
    capture = capture_patcher.start().return_value.__enter__.return_value
    test.addCleanup(capture_patcher.stop)
    return capture


class TestQueryScanJob(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.calls: list[tuple[str, dict[str, Any], Workload | None]] = []
        self.stored: dict[str, Any] = {}
        self.capture = _fake_job_boundaries(self, self.stored)

    def _run(
        self,
        dispatch: dict[str, Any],
        *,
        subqueries: tuple[str, ...] = (),
        team_denom: str = "plan_no_date_bound",
        range_denom: str = "plan_no_event_filter",
        averages_error: BaseException | None = None,
    ) -> None:
        def execute(query: str, arguments: Any = None, *args: Any, **kwargs: Any) -> Any:
            self.calls.append((query, arguments or {}, kwargs.get("workload")))
            if "system.parts" in query:
                if averages_error is not None:
                    raise averages_error
                return _ROW_AVERAGES
            if "timestamp >=" in query or "timestamp <" in query:
                return [[_plan(range_denom)]]
            if "%(scan_team_id)s" in query:
                return [[_plan(team_denom)]]
            for marker, behavior in dispatch.items():
                if marker in query:
                    if isinstance(behavior, BaseException):
                        raise behavior
                    return [[_plan(behavior)]]
            raise AssertionError(f"unexpected EXPLAIN: {query}")

        job = QueryScanJob(
            team=self.team,
            cache_key="cache_key_1",
            executions=(
                Execution(
                    stubbed_sql="STUBBED_MARKER",
                    subqueries=subqueries,
                    values={},
                    rows_read=500_000,
                ),
            ),
            rows_read=500_000,
            duration_ms=19_000,
            trigger="fresh",
            query_kind="HogQLQuery",
            open_filters_placeholder=False,
            insight_id=7,
            dashboard_id=3,
            workload=Workload.ONLINE,
        )
        with mock.patch("posthog.query_scan.job.sync_execute", side_effect=execute):
            run_query_scan(job)

    def _explained(self) -> list[str]:
        return [query for query, _, _ in self.calls]

    @parameterized.expand(
        [
            # The stubbed SQL plans, so the outer plan's finding is stored.
            ("the stubbed sql plans", {"STUBBED_MARKER": "plan_no_date_bound"}, (), ["no_start_date"], True),
            # A finding on a stubbed subquery is merged into the slot.
            (
                "a subquery finding is merged",
                {"STUBBED_MARKER": "plan_event_filter_used", "SUB_MARKER": "plan_no_event_filter"},
                ("SUB_MARKER",),
                ["no_event_filter"],
                True,
            ),
            # Any EXPLAIN error ends the analysis: a slot stored with no plan behind it would say
            # "nothing to fix" for 30 days, so the claim goes and the next slow run analyzes again.
            ("an explain failure fails closed", {"STUBBED_MARKER": _OTHER_ERROR}, (), [], False),
        ]
    )
    def test_analyzes_each_execution(self, _name, dispatch, subqueries, expected_kinds, expected_explain_ok) -> None:
        self._run(dispatch, subqueries=subqueries)

        stored = slot.get(self.team.pk, "cache_key_1", thresholds=FLAG.thresholds_fingerprint)
        if expected_explain_ok:
            assert stored is not None and stored.analysis is not None
            assert [str(finding.kind) for finding in stored.analysis.findings] == expected_kinds
        else:
            assert stored is None

        assert self.capture.call_count == 1
        properties = self.capture.call_args.kwargs["properties"]
        assert self.capture.call_args.kwargs["event"] == "query scan analyzed"
        assert properties["finding_kinds"] == expected_kinds
        assert properties["explain_ok"] is expected_explain_ok
        # The rollout analysis groups the event by these, so they travel from the trigger to here.
        assert (properties["insight_id"], properties["dashboard_id"]) == (7, 3)

    def test_runs_both_denominators_and_stores_the_shares(self) -> None:
        # plan_no_event_filter has a lower timestamp bound, so the range denominator runs with that
        # bound, and both shares reach the slot.
        self._run({"STUBBED_MARKER": "plan_no_event_filter"})

        stored = slot.get(self.team.pk, "cache_key_1", thresholds=FLAG.thresholds_fingerprint)
        assert stored is not None
        assert stored.analysis is not None
        assert stored.analysis.range_share is not None
        assert stored.analysis.project_share is not None
        # The team denominator runs once, unbounded.
        assert any("%(scan_team_id)s" in query and "timestamp" not in query for query, _, _ in self.calls)
        # The range denominator carries the lower bound the plan's Min-Max step reported.
        range_call = next((args for query, args, _ in self.calls if "timestamp >=" in query), None)
        assert range_call is not None
        assert range_call["scan_lower"] == 1788461215
        assert {workload for _, _, workload in self.calls} == {Workload.ONLINE}

    def test_reads_the_row_averages_once_and_survives_their_failure(self) -> None:
        # The average is a table-wide property, so the query runs once, not per execution or EXPLAIN.
        self._run({"STUBBED_MARKER": "plan_persons_join"})
        assert len([query for query in self._explained() if "system.parts" in query]) == 1
        stored = slot.get(self.team.pk, "cache_key_1", thresholds=FLAG.thresholds_fingerprint)
        assert stored is not None and stored.analysis is not None
        assert [str(finding.kind) for finding in stored.analysis.findings] == ["persons_join"]

        # A failed metadata query must not fail the analysis: the gate falls back to raw granules.
        self.calls.clear()
        self.stored.clear()
        self._run({"STUBBED_MARKER": "plan_persons_join"}, averages_error=_OTHER_ERROR)
        stored = slot.get(self.team.pk, "cache_key_1", thresholds=FLAG.thresholds_fingerprint)
        assert stored is not None and stored.analysis is not None
        assert [str(finding.kind) for finding in stored.analysis.findings] == ["persons_join"]


def _explain_unbounded(query: str, arguments: Any = None, *args: Any, **kwargs: Any) -> Any:
    # The real client records every query into the open scope.
    query_stats.record(rows_read=1, duration_ms=1.0)
    if "system.parts" in query:
        return _ROW_AVERAGES
    return [[_plan("plan_no_date_bound")]]


class TestQueryScanInline(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.stored: dict[str, Any] = {}
        self.capture = _fake_job_boundaries(self, self.stored)

    def _job(self, deadline_ms: int) -> QueryScanJob:
        return QueryScanJob(
            team=self.team,
            cache_key="cache_key_1",
            executions=(Execution(stubbed_sql="STUBBED_MARKER", subqueries=(), values={}, rows_read=500_000),),
            rows_read=500_000,
            duration_ms=19_000,
            trigger="fresh",
            query_kind="HogQLQuery",
            open_filters_placeholder=False,
            inline_deadline_ms=deadline_ms,
        )

    def _stored_analysis(self) -> Any:
        stored = slot.get(self.team.pk, "cache_key_1", thresholds=FLAG.thresholds_fingerprint)
        return stored.analysis if stored is not None else None

    def test_stores_the_analysis_before_the_deadline(self) -> None:
        with (
            mock.patch("posthog.query_scan.job.sync_execute", side_effect=_explain_unbounded),
            query_stats.query_stats_scope() as run_stats,
        ):
            outcome = run_query_scan_inline(self._job(deadline_ms=10_000))

        assert outcome == InlineOutcome.STORED
        # The EXPLAINs run on the run's behalf, but they are not its reads, so the run's totals
        # and its `query executed` event must not count them.
        assert run_stats.query_count == 0
        analysis = self._stored_analysis()
        assert analysis is not None
        assert [str(finding.kind) for finding in analysis.findings] == ["no_start_date"]
        properties = self.capture.call_args.kwargs["properties"]
        assert (properties["inline"], properties["deadline_hit"]) == (True, False)

    def test_returns_at_the_deadline_and_stores_once_the_plans_land(self) -> None:
        # The response must not wait on a slow EXPLAIN, and the work already started must not be
        # thrown away: the thread finishes and stores, so the next read of the slot serves the
        # findings without a second analysis.
        release = threading.Event()
        reported = threading.Event()
        self.capture.side_effect = lambda **kwargs: reported.set()

        def explain_once_released(query: str, arguments: Any = None, *args: Any, **kwargs: Any) -> Any:
            if "STUBBED_MARKER" in query:
                assert release.wait(timeout=10)
            return _explain_unbounded(query, arguments, *args, **kwargs)

        with mock.patch("posthog.query_scan.job.sync_execute", side_effect=explain_once_released):
            outcome = run_query_scan_inline(self._job(deadline_ms=20))
            assert outcome == InlineOutcome.PENDING
            assert self._stored_analysis() is None
            release.set()
            assert reported.wait(timeout=10)

        assert self._stored_analysis() is not None
        properties = self.capture.call_args.kwargs["properties"]
        assert (properties["inline"], properties["deadline_hit"]) == (True, True)

    def test_declines_once_the_process_runs_its_share(self) -> None:
        # Slow API runs across many teams would otherwise each start threads that a deadline hit
        # leaves running, so past the cap the run is declined and the trigger enqueues it.
        taken = threading.BoundedSemaphore(1)
        taken.acquire()
        with (
            mock.patch("posthog.query_scan.job._inline_slots", taken),
            mock.patch("posthog.query_scan.job.sync_execute", side_effect=_explain_unbounded) as execute,
        ):
            outcome = run_query_scan_inline(self._job(deadline_ms=10_000))

        assert outcome == InlineOutcome.DECLINED
        execute.assert_not_called()
        assert self._stored_analysis() is None


class TestQueryScanJobOnClickhouse(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Any persons read fires the gate, so the test checks that the plan names the table, not the
        # row arithmetic the fixture tests cover.
        self.flag = QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=0.0)
        self.capture = _fake_job_boundaries(self, {}, flag=self.flag)

    def test_the_real_plan_carries_everything_the_analysis_reads(self) -> None:
        # A saved plan freezes both the printer's and ClickHouse's format, so only a real EXPLAIN of
        # a printed query catches either side changing what the parser reads: the read nodes and
        # their table names, the Min-Max bounds, the primary key's columns and the granule counts.
        _create_person(team=self.team, distinct_ids=["user_1"])
        _create_event(
            team=self.team, event="$pageview", distinct_id="user_1", timestamp=datetime.now(UTC) - timedelta(days=1)
        )
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        DataWarehouseTable.objects.create(
            team=self.team,
            name="customers",
            format="Parquet",
            url_pattern="http://localhost/customers/*.parquet",
            credential=credential,
            columns={"id": "String"},
        )
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        tree = prepare_ast_for_printing(
            parse_select(
                "SELECT count() FROM events AS e JOIN persons AS p ON e.person_id = p.id "
                "JOIN customers AS c ON e.distinct_id = c.id "
                "WHERE e.event = '$pageview' AND e.timestamp >= now() - interval 7 day AND e.timestamp < now() "
                "AND e.distinct_id IN (SELECT distinct_id FROM events "
                "WHERE event = '$pageview' AND timestamp >= now() - interval 7 day)"
            ),
            context,
            dialect="clickhouse",
        )
        assert tree is not None
        stub = stub_in_subqueries(tree)
        job = QueryScanJob(
            team=self.team,
            cache_key="cache_key_1",
            executions=(
                Execution(
                    stubbed_sql=print_prepared_ast(stub.stubbed, context, dialect="clickhouse"),
                    subqueries=tuple(
                        print_prepared_ast(stub_in_subqueries(subquery).stubbed, context, dialect="clickhouse")
                        for subquery in stub.subqueries
                    ),
                    values=context.values,
                    rows_read=500_000,
                ),
            ),
            rows_read=500_000,
            duration_ms=19_000,
            trigger="fresh",
            query_kind="HogQLQuery",
            open_filters_placeholder=False,
        )

        run_query_scan(job)

        stored = slot.get(self.team.pk, "cache_key_1", thresholds=self.flag.thresholds_fingerprint)
        assert stored is not None and stored.analysis is not None
        assert self.capture.call_args.kwargs["properties"]["explain_ok"] is True
        # A share proves the events read and its bounds were found. The only finding is the persons
        # join: the outer read has a start date and an event filter, and so does the subquery.
        assert stored.analysis.range_share is not None
        assert [str(finding.kind) for finding in stored.analysis.findings] == ["persons_join"]
