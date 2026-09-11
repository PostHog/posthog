import json
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from posthog.schema import QueryScanMode, QueryScanSummary

from posthog.query_scan.flag import QueryScanFlag
from posthog.query_scan.serve import attach_scan_slot, scan_summary_with_findings

SHOW = QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=1000, event_ratio=0.1, persons_ratio=0.5)
LOG_ONLY = QueryScanFlag(mode=QueryScanMode.LOG_ONLY, floor_ms=1000, event_ratio=0.1, persons_ratio=0.5)
RAISED_FLOOR = QueryScanFlag(mode=QueryScanMode.SHOW, floor_ms=60_000, event_ratio=0.1, persons_ratio=0.5)


class TestServeScanSummary(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.redis = mock.Mock()
        self.redis.get.return_value = json.dumps(
            {
                "version": 1,
                "status": "done",
                "thresholds": SHOW.thresholds_fingerprint,
                "range_share": 0.8,
                "project_share": 0.25,
                "findings": [
                    {
                        "type": "query_scan",
                        "kind": "no_event_filter",
                        "message": "This query read every event in its date range.",
                        "fix": "Add an event filter naming the events this question is about.",
                    }
                ],
            }
        )
        patcher = mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _cached_summary(self) -> dict:
        # What a run stored while the flag said "show" and the floor was a second.
        return {"mode": "show", "rows_read": 41_200, "duration_ms": 19_000, "status": "pending"}

    def _cached_response(self) -> SimpleNamespace:
        return SimpleNamespace(
            query_scan=QueryScanSummary(mode="show", rows_read=41_200, duration_ms=19_000, status="pending"),
            cache_key="cache_key_1",
            warnings=[],
        )

    @parameterized.expand(
        [
            ("the flag went off", None, None, None),
            # `log_only` collects the analysis without showing it to anyone.
            ("the mode was downgraded", LOG_ONLY, ("log_only", "done"), []),
            # Below the floor nothing reads the slot, so no status can be confirmed.
            ("the floor was raised", RAISED_FLOOR, ("show", None), []),
            ("nothing moved", SHOW, ("show", "done"), ["no_event_filter"]),
        ]
    )
    def test_a_cached_summary_is_corrected_against_the_live_flag(self, _name, flag, expected, expected_kinds) -> None:
        response = self._cached_response()

        with mock.patch("posthog.query_scan.serve.get_query_scan_flag", return_value=flag):
            attach_scan_slot(self.team, response)
            folded = scan_summary_with_findings(self.team, self._cached_summary(), "cache_key_1")

        if expected is None:
            assert folded is None
            assert response.query_scan is None
            return
        assert response.query_scan is not None
        assert (response.query_scan.mode, response.query_scan.status) == expected
        assert [warning.kind for warning in response.warnings] == expected_kinds
        assert folded is not None
        assert (folded["mode"], folded["status"]) == expected
        assert [warning["kind"] for warning in folded.get("warnings", [])] == expected_kinds
        # The findings come with the message "Fix with AI" sends, built here so no client keeps its own copy.
        assert (response.query_scan.assistant_prompt is not None) is bool(expected_kinds)
        assert ("assistant_prompt" in folded) is bool(expected_kinds)

    def test_a_done_slot_puts_the_shares_on_the_summary(self) -> None:
        # The shares are how the stat line says what fraction of the range a query read, so they
        # have to reach the served summary.
        response = self._cached_response()

        with mock.patch("posthog.query_scan.serve.get_query_scan_flag", return_value=SHOW):
            attach_scan_slot(self.team, response)
            folded = scan_summary_with_findings(self.team, self._cached_summary(), "cache_key_1")

        assert (response.query_scan.range_share, response.query_scan.project_share) == (0.8, 0.25)
        assert folded is not None
        assert (folded["range_share"], folded["project_share"]) == (0.8, 0.25)
