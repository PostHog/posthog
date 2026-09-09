from types import SimpleNamespace
from typing import cast

import pytest
from unittest.mock import patch

from posthog.llm.wizard_email_verification import wizard_email_unverified
from posthog.models.user import User


def _user(is_email_verified: bool | None = False, email: str = "person@example.com") -> User:
    # A stub keeps these off the database.
    return cast(User, SimpleNamespace(is_email_verified=is_email_verified, email=email))


class TestWizardEmailUnverified:
    @pytest.mark.parametrize(
        "is_email_verified,demo,email_available,verification_disabled,expected",
        [
            (True, False, True, False, False),
            (False, False, True, False, True),
            # A pre-verification account reads None. The login flow trusts those, so
            # refusing them here would lock out accounts that predate the field.
            (None, False, True, False, False),
            (True, False, False, True, False),
            # Every way the question was never asked, each leaving a legitimate
            # account unverified.
            (False, True, True, False, False),
            (False, False, False, False, False),
            (False, False, True, True, False),
        ],
    )
    def test_refuses_only_an_account_that_was_asked_to_verify_and_did_not(
        self, is_email_verified, demo, email_available, verification_disabled, expected
    ):
        with (
            patch("posthog.llm.wizard_email_verification.settings.DEMO", demo),
            patch("posthog.llm.wizard_email_verification.is_email_available", return_value=email_available),
            patch(
                "posthog.llm.wizard_email_verification.is_email_verification_disabled",
                return_value=verification_disabled,
            ),
        ):
            assert wizard_email_unverified(user=_user(is_email_verified), surface="gateway_token") is expected

    def test_a_caller_without_a_user_is_allowed(self):
        assert wizard_email_unverified(user=None, surface="query") is False

    @pytest.mark.parametrize("failing_lookup", ["is_email_available", "is_email_verification_disabled"])
    def test_a_lookup_failure_allows_rather_than_refusing_every_run(self, failing_lookup):
        # Losing either lookup must not refuse the fleet.
        with (
            patch("posthog.llm.wizard_email_verification.settings.DEMO", False),
            patch("posthog.llm.wizard_email_verification.is_email_available", return_value=True),
            patch("posthog.llm.wizard_email_verification.is_email_verification_disabled", return_value=False),
            patch(f"posthog.llm.wizard_email_verification.{failing_lookup}", side_effect=Exception("unavailable")),
        ):
            assert wizard_email_unverified(user=_user(is_email_verified=False), surface="cloud_run") is False

    def test_a_verified_account_reaches_the_gateway_without_either_lookup(self):
        # Moving the free field check below the lookups would put them on the hot path.
        with (
            patch("posthog.llm.wizard_email_verification.is_email_available") as email_available,
            patch("posthog.llm.wizard_email_verification.is_email_verification_disabled") as verification_disabled,
        ):
            assert wizard_email_unverified(user=_user(is_email_verified=True), surface="oauth_authorize") is False

        email_available.assert_not_called()
        verification_disabled.assert_not_called()
