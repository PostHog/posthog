from types import SimpleNamespace

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.tasks.email import send_email_verification


class TestEmailVerificationRecipient(SimpleTestCase):
    @parameterized.expand(
        [
            # (db_pending_email, target_email, expected_recipient)
            # A concurrent email change may have drifted pending_email to an attacker-controlled
            # address; the verification must still go only to the address the token authorizes.
            ("pinned_target_wins_over_drifted_pending_email", "attacker@x.com", "victim@x.com", "victim@x.com"),
            # Callers that don't pin a target (signup, auth, admin) keep the existing behavior.
            ("defaults_to_pending_email_without_target", "new@x.com", None, "new@x.com"),
        ]
    )
    def test_verification_recipient(
        self, _name: str, db_pending_email: str, target_email: str | None, expected: str
    ) -> None:
        user = SimpleNamespace(
            pk=1,
            uuid="u",
            pending_email=db_pending_email,
            email="original@x.com",
            distinct_id="d",
            current_organization=SimpleNamespace(id="org"),
        )
        with (
            patch("posthog.tasks.email.User.objects.get", return_value=user),
            patch("posthog.tasks.email.posthoganalytics.capture"),
            patch("posthog.tasks.email.EmailMessage") as MockEmailMessage,
        ):
            send_email_verification(user.pk, "token", target_email=target_email)

        MockEmailMessage.return_value.add_user_recipient.assert_called_once_with(user, email_override=expected)
