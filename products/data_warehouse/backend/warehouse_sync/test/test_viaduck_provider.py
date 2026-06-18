from posthog.test.base import BaseTest

from products.data_warehouse.backend.warehouse_sync.viaduck_provider import (
    ViaduckSyncStatusProvider,
    viaduck_state_to_sync_state,
)


class TestViaduckMapping(BaseTest):
    def test_health_maps_to_neutral_state(self) -> None:
        assert viaduck_state_to_sync_state("healthy", 42, 0.0) == "caught_up"
        assert viaduck_state_to_sync_state("buffering", 42, 0.0) == "caught_up"
        assert viaduck_state_to_sync_state("flushing", 42, 0.0) == "caught_up"
        assert viaduck_state_to_sync_state("lagging", 42, 30.0) == "lagging"
        assert viaduck_state_to_sync_state("error", 42, 0.0) == "error"

    def test_cursor_zero_is_seeding(self) -> None:
        assert viaduck_state_to_sync_state("buffering", 0, 0.0) == "seeding"

    def test_get_status_not_started_without_source(self) -> None:
        dto = ViaduckSyncStatusProvider().get_status("org-1")
        assert dto.backend == "viaduck"
        assert dto.state == "not_started"
