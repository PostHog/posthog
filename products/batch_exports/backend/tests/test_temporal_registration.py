import importlib

from posthog.temporal.common.registration import TemporalRegistration

from products.batch_exports.backend.facade import temporal as temporal_facade


def test_worker_hosts_no_batch_export_code_while_batch_exports_are_off(settings):
    settings.BATCH_EXPORTS_ENABLED = False
    try:
        importlib.reload(temporal_facade)

        assert temporal_facade.TEMPORAL == TemporalRegistration()
        assert temporal_facade.WORKFLOWS == []
    finally:
        settings.BATCH_EXPORTS_ENABLED = True
        importlib.reload(temporal_facade)
    assert temporal_facade.TEMPORAL.queues
