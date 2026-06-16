import pytest

from posthog.temporal.data_imports.sources.github.source import GithubSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestGithubSource:
    def setup_method(self):
        self.source = GithubSource()

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GITHUB

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "404 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "error_message,expected_match",
        [
            # GitHub returns this body verbatim when the App installation no longer exists; the matcher
            # in external_data_job does a substring check against the raised GitHubIntegrationError message.
            (
                'Failed to refresh installation token: {"message":"Not Found",'
                '"documentation_url":"https://docs.github.com/rest/reference/apps'
                '#create-an-installation-access-token-for-an-app","status":"404"}',
                True,
            ),
            # A 5xx during token refresh is transient and must remain retryable, so the not-found match
            # must not be triggered by the generic "Failed to refresh installation token" prefix alone.
            (
                'Failed to refresh installation token: {"message":"Server Error","status":"500"}',
                False,
            ),
        ],
    )
    def test_installation_token_refresh_non_retryable_matching(self, error_message, expected_match):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in error_message for key in non_retryable) == expected_match
