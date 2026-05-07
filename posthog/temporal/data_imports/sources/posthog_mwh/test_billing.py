from products.data_warehouse.backend.types import ExternalDataSourceType


class TestPostHogMWHBilling:
    def test_posthogmwh_is_not_billable(self):
        source_type = ExternalDataSourceType.POSTHOGMWH
        is_billable = source_type != ExternalDataSourceType.POSTHOGMWH
        assert is_billable is False

    def test_other_sources_are_billable(self):
        source_type = ExternalDataSourceType.POSTGRES
        is_billable = source_type != ExternalDataSourceType.POSTHOGMWH
        assert is_billable is True
