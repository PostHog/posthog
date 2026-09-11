from typing import Any

from unittest import mock

from django.test import SimpleTestCase

from posthog.schema import QueryScanFindingKind, QueryScanStatus, QueryScanWarning

from posthog.query_scan.slot import (
    QueryScanSlot,
    get as get_slot,
    set_done,
)


class TestQueryScanSlotRoundTrip(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.stored: dict[str, Any] = {}
        redis = mock.Mock()
        redis.get.side_effect = lambda key: self.stored.get(key)
        redis.set.side_effect = lambda key, value, ex=None, nx=False: self.stored.__setitem__(key, value)
        patcher = mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_done_slot_round_trips_its_shares_and_findings(self) -> None:
        # The shares and the killed flag are what a served response and the scan endpoint read back,
        # so a write that dropped them on the way through Redis would show a blank analysis.
        finding = QueryScanWarning(
            kind=QueryScanFindingKind.NO_EVENT_FILTER,
            message="This query read every event.",
            fix="Add an event filter.",
        )
        set_done(
            1,
            "cache_key_1",
            QueryScanSlot(
                status=QueryScanStatus.DONE,
                range_share=0.42,
                project_share=0.13,
                findings=(finding,),
                killed=True,
            ),
        )

        stored = get_slot(1, "cache_key_1")

        assert stored is not None
        assert stored.status == QueryScanStatus.DONE
        assert stored.range_share == 0.42
        assert stored.project_share == 0.13
        assert stored.killed is True
        assert [str(f.kind) for f in stored.findings] == ["no_event_filter"]
