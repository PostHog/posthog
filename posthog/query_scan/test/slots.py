from unittest import mock

from posthog.schema import QueryScanAnalysis

from posthog.query_scan.slot import set_done


def stored_slot(analysis: QueryScanAnalysis) -> str:
    """What Redis holds for ``analysis``, as the job writes it, for a test that mocks the read side."""
    client = mock.Mock()
    with mock.patch("posthog.query_scan.slot.query_cache_raw_client", return_value=client):
        set_done(0, "cache_key", thresholds="0.1:0.5", analysis=analysis)
    return client.set.call_args.args[1]
