import pytest

from posthog.temporal.data_imports.sources.doit.source import DoItSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestDoItSource:
    def setup_method(self):
        self.source = DoItSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DOIT

    @pytest.mark.parametrize("pattern", ["Report no longer exists"])
    def test_non_retryable_errors_includes_pattern(self, pattern):
        errors = self.source.get_non_retryable_errors()

        assert pattern in errors
