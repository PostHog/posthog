from typing import Any

from unittest import mock

from django.test import SimpleTestCase

from posthog.schema import QueryScanAnalysis, QueryScanFindingKind, QueryScanWarning

from posthog.query_scan.slot import (
    get as get_slot,
    set_done,
    set_pending,
)


class TestQueryScanSlotRoundTrip(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.stored: dict[str, Any] = {}
        redis = mock.Mock()
        redis.get.side_effect = lambda key: self.stored.get(key)

        def set_unless_claimed(key: str, value: str, ex: int | None = None, nx: bool = False) -> bool | None:
            # Redis answers a conditional write that lost with None and any other write with True.
            if nx and key in self.stored:
                return None
            self.stored[key] = value
            return True

        redis.set.side_effect = set_unless_claimed
        patcher = mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_stored_analysis_round_trips_its_shares_and_findings(self) -> None:
        # The shares and findings are what a served response and the scan endpoint read back, so a
        # write that dropped them on the way through Redis would show a blank analysis.
        finding = QueryScanWarning(
            kind=QueryScanFindingKind.NO_EVENT_FILTER,
            message="This query read every event.",
            fix="Add an event filter.",
            actionable=True,
        )
        set_done(
            1,
            "cache_key_1",
            thresholds="0.1:0.5",
            analysis=QueryScanAnalysis(findings=[finding], range_share=0.42, project_share=0.13),
        )

        stored = get_slot(1, "cache_key_1", thresholds="0.1:0.5")

        assert stored is not None and stored.analysis is not None
        assert (stored.analysis.range_share, stored.analysis.project_share) == (0.42, 0.13)
        assert [str(finding.kind) for finding in stored.analysis.findings] == ["no_event_filter"]

    def test_a_claim_reads_back_as_a_slot_with_no_analysis(self) -> None:
        # The scan endpoint tells "not yet" from "nothing stored" by this, so a claim must read
        # back as a slot rather than as nothing.
        assert set_pending(1, "cache_key_1", thresholds="0.1:0.5") is True

        stored = get_slot(1, "cache_key_1", thresholds="0.1:0.5")

        assert stored is not None
        assert stored.analysis is None
