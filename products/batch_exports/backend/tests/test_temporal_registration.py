import pytest

from posthog.temporal.common.registration import load_registrations


@pytest.mark.parametrize("enabled", [True, False])
def test_worker_hosts_batch_export_code_only_while_batch_exports_are_on(settings, enabled: bool):
    settings.BATCH_EXPORTS_ENABLED = enabled

    # The uncached function, because the cached result outlives the setting.
    assert ("batch_exports" in load_registrations.__wrapped__()) is enabled
