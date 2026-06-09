from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import ANY, MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.invite_postpone import MAX_POSTPONE_HORIZON_DAYS
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.organization_invite import OrganizationInvite


def _token_for(invite_id: object, expiry: timedelta = timedelta(days=3)) -> str:
    return encode_jwt({"invite_id": str(invite_id)}, expiry_delta=expiry, audience=PosthogJwtAudience.INVITE_POSTPONE)


@freeze_time("2025-01-01")
class TestInvitePostponeAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The postpone page is reached by an unauthenticated recipient clicking the email link.
        self.client.logout()
        self.invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="recipient@posthog.com",
            created_by=self.user,
        )

    def test_get_returns_invite_info_for_valid_token(self) -> None:
        response = self.client.get(f"/api/invite_postpone?token={_token_for(self.invite.id)}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["organization_name"], self.organization.name)
        self.assertEqual(data["target_email"], "recipient@posthog.com")
        self.assertIsNone(data["scheduled_send_at"])
        self.assertIn("expires_at", data)

    @parameterized.expand([("empty", ""), ("garbage", "not-a-valid-jwt")])
    def test_get_rejects_invalid_token(self, _name: str, token: str) -> None:
        response = self.client.get(f"/api/invite_postpone?token={token}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_get_rejects_expired_invite(self) -> None:
        OrganizationInvite.objects.filter(id=self.invite.id).update(expires_at=timezone.now() - timedelta(minutes=1))
        response = self.client.get(f"/api/invite_postpone?token={_token_for(self.invite.id)}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "expired")

    def test_post_schedules_send_and_extends_expiry(self) -> None:
        send_at = timezone.now() + timedelta(hours=3)
        response = self.client.post(
            "/api/invite_postpone", {"token": _token_for(self.invite.id), "send_at": send_at.isoformat()}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.invite.refresh_from_db()
        self.assertIsNotNone(self.invite.scheduled_send_at)
        # Validity is extended past the new send time so the rescheduled link still works.
        assert self.invite.expires_at is not None
        self.assertGreater(self.invite.expires_at, send_at)

    def test_post_works_with_trailing_slash(self) -> None:
        # The frontend api client appends a trailing slash to POST URLs without a query string,
        # so the route must accept /api/invite_postpone/ as well as /api/invite_postpone.
        send_at = timezone.now() + timedelta(hours=3)
        response = self.client.post(
            "/api/invite_postpone/", {"token": _token_for(self.invite.id), "send_at": send_at.isoformat()}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.invite.refresh_from_db()
        self.assertIsNotNone(self.invite.scheduled_send_at)

    @override_settings(DEBUG=True)
    def test_post_in_debug_forces_one_minute_schedule(self) -> None:
        # In dev a postpone always comes back in ~1 minute, regardless of the requested time.
        send_at = timezone.now() + timedelta(days=2)
        response = self.client.post(
            "/api/invite_postpone", {"token": _token_for(self.invite.id), "send_at": send_at.isoformat()}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.invite.refresh_from_db()
        self.assertEqual(self.invite.scheduled_send_at, timezone.now() + timedelta(minutes=1))

    @parameterized.expand(
        [
            ("past", timedelta(hours=-1)),
            ("beyond_horizon", timedelta(days=MAX_POSTPONE_HORIZON_DAYS + 1)),
        ]
    )
    def test_post_rejects_out_of_bounds_send_at(self, _name: str, offset: timedelta) -> None:
        send_at = timezone.now() + offset
        response = self.client.post(
            "/api/invite_postpone", {"token": _token_for(self.invite.id), "send_at": send_at.isoformat()}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.invite.refresh_from_db()
        self.assertIsNone(self.invite.scheduled_send_at)

    @patch("posthoganalytics.capture")
    def test_post_captures_postpone_event(self, mock_capture: MagicMock) -> None:
        send_at = timezone.now() + timedelta(hours=1)
        response = self.client.post(
            "/api/invite_postpone",
            {"token": _token_for(self.invite.id), "send_at": send_at.isoformat(), "option": "hour"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_capture.assert_called_once_with(
            event="organization invite postponed",
            distinct_id=f"invite_{self.invite.id}",
            properties={
                "invite_id": str(self.invite.id),
                "option": "hour",
                "prior_postpone_count": 0,
                "hours_until_resend": 1.0,
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )

    @patch("posthoganalytics.capture")
    def test_post_does_not_capture_when_token_invalid(self, mock_capture: MagicMock) -> None:
        send_at = timezone.now() + timedelta(hours=1)
        response = self.client.post("/api/invite_postpone", {"token": "bad", "send_at": send_at.isoformat()})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_capture.assert_not_called()

    def test_post_rejects_invalid_token(self) -> None:
        send_at = timezone.now() + timedelta(hours=3)
        response = self.client.post("/api/invite_postpone", {"token": "bad", "send_at": send_at.isoformat()})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_post_rejects_expired_invite(self) -> None:
        OrganizationInvite.objects.filter(id=self.invite.id).update(expires_at=timezone.now() - timedelta(minutes=1))
        send_at = timezone.now() + timedelta(hours=3)
        response = self.client.post(
            "/api/invite_postpone", {"token": _token_for(self.invite.id), "send_at": send_at.isoformat()}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "expired")
