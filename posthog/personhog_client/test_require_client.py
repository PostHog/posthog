from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.personhog_client.client import PersonHogNotConfiguredError, require_personhog_client


class TestRequirePersonHogClient(SimpleTestCase):
    def test_raises_typed_error_when_not_configured(self) -> None:
        with patch("posthog.personhog_client.client.get_personhog_client", return_value=None):
            with self.assertRaises(PersonHogNotConfiguredError):
                require_personhog_client()

    def test_typed_error_is_runtime_error_subclass(self) -> None:
        # Existing `except RuntimeError` handlers must keep catching it.
        self.assertTrue(issubclass(PersonHogNotConfiguredError, RuntimeError))

    def test_error_name_matches_non_retryable_retry_policy_entries(self) -> None:
        # Temporal matches non_retryable_error_types on the exception class name, so a rename of
        # PersonHogNotConfiguredError must stay in sync with these strings or team/person deletions
        # would retry the permanent misconfiguration forever and flood error tracking.
        from posthog.temporal.delete_teams.workflows import DELETE_RETRY_POLICY

        self.assertIn(PersonHogNotConfiguredError.__name__, DELETE_RETRY_POLICY.non_retryable_error_types or [])
