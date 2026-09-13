from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from posthog.schema import QueryScanMode

from posthog.errors import InternalCHQueryError
from posthog.query_scan import slot
from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.job import Execution, QueryScanJob, run_query_scan

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


class TestQueryScanJob(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.stored: dict[str, Any] = {}
        redis = mock.Mock()
        redis.get.side_effect = lambda key: self.stored.get(key)
        redis.set.side_effect = lambda key, value, ex=None, nx=False: self.stored.__setitem__(key, value)
        patcher = mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=redis)
        patcher.start()
        self.addCleanup(patcher.stop)

        flag_patcher = mock.patch("posthog.query_scan.job.get_query_scan_flag", return_value=FLAG)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

        capture_patcher = mock.patch("posthog.query_scan.job.ph_scoped_capture")
        self.capture = capture_patcher.start().return_value.__enter__.return_value
        self.addCleanup(capture_patcher.stop)

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
            self.calls.append((query, arguments or {}))
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
        )
        with mock.patch("posthog.query_scan.job.sync_execute", side_effect=execute):
            run_query_scan(job)

    def _explained(self) -> list[str]:
        return [query for query, _ in self.calls]

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
            # Any EXPLAIN error ends the analysis for that execution, findings and all.
            ("an explain failure fails closed", {"STUBBED_MARKER": _OTHER_ERROR}, (), [], False),
        ]
    )
    def test_analyzes_each_execution(self, _name, dispatch, subqueries, expected_kinds, expected_explain_ok) -> None:
        self._run(dispatch, subqueries=subqueries)

        stored = slot.get(self.team.pk, "cache_key_1", thresholds=FLAG.thresholds_fingerprint)
        assert stored is not None
        assert stored.status == "done"
        assert [str(finding.kind) for finding in stored.findings] == expected_kinds

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
        assert stored.range_share is not None
        assert stored.project_share is not None
        # The team denominator runs once, unbounded.
        assert any("%(scan_team_id)s" in query and "timestamp" not in query for query, _ in self.calls)
        # The range denominator carries the lower bound the plan's Min-Max step reported.
        range_call = next((args for query, args in self.calls if "timestamp >=" in query), None)
        assert range_call is not None
        assert range_call["scan_lower"] == 1788461215

    def test_reads_the_row_averages_once_and_survives_their_failure(self) -> None:
        # The average is a table-wide property, so the query runs once, not per execution or EXPLAIN.
        self._run({"STUBBED_MARKER": "plan_persons_join"})
        assert len([query for query in self._explained() if "system.parts" in query]) == 1
        stored = slot.get(self.team.pk, "cache_key_1", thresholds=FLAG.thresholds_fingerprint)
        assert stored is not None and stored.status == "done"
        assert [str(finding.kind) for finding in stored.findings] == ["persons_join"]

        # A failed metadata query must not fail the analysis: the gate falls back to raw granules.
        self.calls.clear()
        self.stored.clear()
        self._run({"STUBBED_MARKER": "plan_persons_join"}, averages_error=_OTHER_ERROR)
        stored = slot.get(self.team.pk, "cache_key_1", thresholds=FLAG.thresholds_fingerprint)
        assert stored is not None and stored.status == "done"
        assert [str(finding.kind) for finding in stored.findings] == ["persons_join"]
