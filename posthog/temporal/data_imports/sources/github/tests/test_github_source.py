import pytest

from posthog.temporal.data_imports.sources.generated_configs import GithubAuthMethodConfig, GithubSourceConfig
from posthog.temporal.data_imports.sources.github.source import GithubSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestGithubSource:
    def setup_method(self):
        self.source = GithubSource()
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GITHUB

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "404 Client Error",
            "Bad credentials",
            "Missing GitHub integration ID",
            "GITHUB_APP_CLIENT_ID is not configured",
            "GITHUB_APP_PRIVATE_KEY is not configured",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_oauth_without_integration_id_raises_non_retryable_error(self):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(selection="oauth", github_integration_id=None),
            repository="owner/repo",
        )

        with pytest.raises(ValueError) as exc_info:
            self.source._get_access_token(config, self.team_id)

        # The raised message must stay a recognised non-retryable substring so a misconfigured
        # OAuth source stops retrying instead of failing forever.
        assert any(key in str(exc_info.value) for key in self.source.get_non_retryable_errors())
