import pytest

from posthog.temporal.data_imports.sources.github.source import GithubSource


class TestGithubSource:
    def setup_method(self):
        self.source = GithubSource()

    @pytest.mark.parametrize(
        "pattern",
        [
            "401 Client Error",
            "403 Client Error",
            "404 Client Error",
            "Bad credentials",
            "Missing GitHub integration ID",
            "Integration not found",
            "GitHub access token not found",
        ],
    )
    def test_non_retryable_errors_includes_pattern(self, pattern):
        errors = self.source.get_non_retryable_errors()

        assert pattern in errors

    @pytest.mark.parametrize(
        "error_message",
        [
            "Integration not found: 59986",
            "Integration not found: 165563",
        ],
    )
    def test_deleted_integration_is_non_retryable(self, error_message):
        """OAuthMixin.get_oauth_integration raises ValueError("Integration not found: <id>") when the
        linked GitHub integration row has been deleted. The id is volatile, so we match on the stable
        prefix; retrying can't recover a deleted integration."""
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable_errors), (
            f"Expected '{error_message}' to match a non-retryable pattern"
        )

    def test_transient_failures_are_retryable(self):
        """Connection/timeout errors are infrastructure noise — they must stay retryable so they
        don't get swallowed as terminal config errors."""
        non_retryable_errors = self.source.get_non_retryable_errors()

        for error_message in (
            "HTTPSConnectionPool(host='api.github.com', port=443): Read timed out.",
            "Connection aborted. ConnectionResetError(104, 'Connection reset by peer')",
        ):
            assert not any(pattern in error_message for pattern in non_retryable_errors), (
                f"'{error_message}' must not match a non-retryable pattern"
            )
