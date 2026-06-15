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
            "Missing personal access token",
            "Missing GitHub integration ID",
            "Missing integration ID",
            "Integration not found",
            "GitHub access token not found",
        ],
    )
    def test_non_retryable_errors_present(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "observed_error",
        [
            # A deleted/disconnected OAuth integration the source still references — the id varies
            # per source, so the stable substring "Integration not found" must be what we match on.
            "Integration not found: 61455",
            "ValueError: Integration not found: 160881",
            "Missing GitHub integration ID",
            "Missing integration ID",
            "GitHub access token not found",
        ],
    )
    def test_credential_config_errors_are_non_retryable(self, observed_error):
        # Mirrors the substring match in external_data_job.update_external_data_job_model.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "transient_error",
        [
            "500 Server Error for url: https://api.github.com/repos/owner/repo/commits",
            "Connection reset by peer",
            "Read timed out",
        ],
    )
    def test_transient_errors_stay_retryable(self, transient_error):
        # Transient infrastructure failures must not be swallowed — they should keep retrying.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in transient_error for key in non_retryable_errors)
