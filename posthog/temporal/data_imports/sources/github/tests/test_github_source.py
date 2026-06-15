import pytest

from posthog.temporal.data_imports.sources.github.source import GithubSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestGithubSource:
    def setup_method(self):
        self.source = GithubSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GITHUB

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "404 Client Error",
            "Bad credentials",
            "GITHUB_APP_CLIENT_ID is not configured",
            "GITHUB_APP_PRIVATE_KEY is not configured",
        ],
    )
    def test_non_retryable_errors_contains_key(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "internal_error",
        [
            "[ErrorDetail(string='GITHUB_APP_CLIENT_ID is not configured', code='invalid')]",
            "[ErrorDetail(string='GITHUB_APP_PRIVATE_KEY is not configured', code='invalid')]",
        ],
    )
    def test_app_not_configured_is_recognised_as_non_retryable(self, internal_error):
        # Mirrors the substring match done in external_data_job.update_external_data_job_model.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(pattern in internal_error for pattern in non_retryable_errors)
