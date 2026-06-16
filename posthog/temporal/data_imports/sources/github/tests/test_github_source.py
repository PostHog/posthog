import pytest
from unittest import mock

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
            "Missing personal access token",
            "GitHub access token not found",
            "Integration not found",
            "Missing integration ID",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_access_token_missing_integration_id_is_non_retryable(self):
        # OAuth selected but no account connected (or integration deleted) — the message
        # raised here must match a get_non_retryable_errors key so the schema stops retrying.
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="oauth", personal_access_token=""),
            repository="owner/repo",
        )

        with pytest.raises(ValueError, match="Missing GitHub integration ID") as exc_info:
            self.source._get_access_token(config, self.team_id)

        assert any(key in str(exc_info.value) for key in self.source.get_non_retryable_errors())

    def test_get_access_token_missing_pat_is_non_retryable(self):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token=""),
            repository="owner/repo",
        )

        with pytest.raises(ValueError, match="Missing personal access token") as exc_info:
            self.source._get_access_token(config, self.team_id)

        assert any(key in str(exc_info.value) for key in self.source.get_non_retryable_errors())

    def test_get_access_token_returns_pat(self):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(
                github_integration_id=None, selection="pat", personal_access_token="github_pat_123"
            ),
            repository="owner/repo",
        )

        assert self.source._get_access_token(config, self.team_id) == "github_pat_123"

    @mock.patch("posthog.temporal.data_imports.sources.github.source.GitHubIntegration")
    def test_get_access_token_via_oauth(self, mock_github_integration):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=42, selection="oauth", personal_access_token=""),
            repository="owner/repo",
        )

        integration = mock.MagicMock()
        integration.access_token = "gho_token"
        with mock.patch.object(self.source, "get_oauth_integration", return_value=integration):
            mock_github_integration.return_value.access_token_expired.return_value = False
            assert self.source._get_access_token(config, self.team_id) == "gho_token"
