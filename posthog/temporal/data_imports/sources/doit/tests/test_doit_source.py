from posthog.temporal.data_imports.sources.doit.source import DoItSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestDoItSource:
    def setup_method(self):
        self.source = DoItSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DOIT

    def test_non_retryable_errors(self):
        errors = self.source.get_non_retryable_errors()
        assert "Report no longer exists" in errors
