import json
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from posthog.schema import QueryScanSummary

from posthog.query_scan.flag import QueryScanFlag, QueryScanMode
from posthog.query_scan.serve import hydrate_response_scan, hydrate_scan_summary

SHOW = QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=0.5)
LOG_ONLY = QueryScanFlag(mode=QueryScanMode.LOG_ONLY, floor_ms=1000, event_ratio=0.1, persons_ratio=0.5)

STORED_ANALYSIS = json.dumps(
    {
        "analysis": {
            "range_share": 0.8,
            "project_share": 0.25,
            "findings": [
                {
                    "kind": "no_event_filter",
                    "message": "This query read every event in its date range.",
                    "fix": "Add an event filter naming the events this question is about.",
                    "actionable": True,
                }
            ],
        },
    }
)
PENDING = json.dumps({"pending": True})


class TestHydrateScanSummary(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.redis = mock.Mock()
        self.redis.get.return_value = STORED_ANALYSIS
        patcher = mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _cached_summary(self, **overrides: Any) -> dict[str, Any]:
        # What a slow run stored with its result.
        return {"rows_read": 41_200, "duration_ms": 19_000, "analysis_requested": True, **overrides}

    def _cached_response(self, **overrides: Any) -> SimpleNamespace:
        return SimpleNamespace(
            query_scan=QueryScanSummary(**self._cached_summary(**overrides)), cache_key="cache_key_1"
        )

    @parameterized.expand(
        [
            ("the flag went off", None, None),
            # `log_only` collects the analysis without showing it to anyone.
            ("the mode was downgraded", LOG_ONLY, None),
            ("nothing moved", SHOW, ["no_event_filter"]),
        ]
    )
    def test_a_cached_summary_is_served_under_the_live_flag(self, _name, flag, expected_kinds) -> None:
        response = self._cached_response()

        with mock.patch("posthog.query_scan.serve.get_query_scan_flag", return_value=flag):
            hydrate_response_scan(self.team, response)
            folded = hydrate_scan_summary(self.team, self._cached_summary(), "cache_key_1")

        if expected_kinds is None:
            assert response.query_scan is None
            assert folded is None
            return
        assert [finding.kind for finding in response.query_scan.analysis.findings] == expected_kinds
        assert folded is not None
        assert [finding["kind"] for finding in folded["analysis"]["findings"]] == expected_kinds
        assert (response.query_scan.analysis.range_share, folded["analysis"]["project_share"]) == (0.8, 0.25)
        # The findings come with the message "Fix with AI" sends, built here so no client keeps its own copy.
        assert "- no_event_filter:" in response.query_scan.analysis.assistant_prompt

    @parameterized.expand(
        [
            # A run that asked for nothing costs no Redis read, however long it took.
            ("no analysis was requested", {"analysis_requested": False}, STORED_ANALYSIS, 0),
            ("the job is still running", {}, PENDING, 1),
            ("the slot expired", {}, None, 1),
        ]
    )
    def test_a_summary_without_a_stored_analysis_is_served_as_it_is(
        self, _name, overrides: dict[str, Any], stored: str | None, redis_reads: int
    ) -> None:
        self.redis.get.return_value = stored
        response = self._cached_response(**overrides)

        with mock.patch("posthog.query_scan.serve.get_query_scan_flag", return_value=SHOW):
            hydrate_response_scan(self.team, response)

        assert response.query_scan is not None
        assert response.query_scan.analysis is None
        assert self.redis.get.call_count == redis_reads

    def test_the_prompt_describes_the_run_being_served(self) -> None:
        # The slot can hold the analysis of a run that finished while this one was stopped, and the
        # other way round, so the prompt's run line follows the summary.
        response = self._cached_response(killed=True)

        with mock.patch("posthog.query_scan.serve.get_query_scan_flag", return_value=SHOW):
            hydrate_response_scan(self.team, response)

        assert "ClickHouse stopped this query after" in response.query_scan.analysis.assistant_prompt
