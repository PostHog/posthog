from unittest import mock

from posthog.query_scan.slot import QueryScanSlot, set_done


def stored_slot(slot: QueryScanSlot) -> str:
    """What Redis holds for ``slot``, as the job writes it, for a test that mocks the read side."""
    client = mock.Mock()
    with mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=client):
        set_done(0, "cache_key", thresholds="0.1:0.5", slot=slot)
    return client.set.call_args.args[1]
