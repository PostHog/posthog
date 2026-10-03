import json
import secrets
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.leaked_key import PUBLIC_REPORT_MORE_INFO
from posthog.api.secret_revocation import (
    CANONICAL_OAUTH_ACCESS_TOKEN,
    CANONICAL_OAUTH_REFRESH_TOKEN,
    CANONICAL_PERSONAL_API_KEY,
    CANONICAL_PROJECT_SECRET_API_KEY,
)
from posthog.models import PersonalAPIKey
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    OAuthRefreshToken,
    find_oauth_access_token,
    find_oauth_refresh_token,
)
from posthog.models.personal_api_key import LEGACY_PERSONAL_API_KEY_SALT, find_personal_api_key
from posthog.models.project_secret_api_key import find_project_secret_api_key
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
from posthog.rate_limit import LeakedKeyReportThrottle
from posthog.test.api_keys import create_project_secret_api_key


class TestPublicLeakedKeyReport(APIBaseTest):
    # Every case must exercise the anonymous path this endpoint exists to serve. With the
    # default force-login, dropping `authentication_classes`/`permission_classes` from the
    # view would fall back to DRF's authenticated-only defaults and no test would notice.
    CONFIG_AUTO_LOGIN = False

    def _create_oauth_app(self) -> OAuthApplication:
        return OAuthApplication.objects.create(
            name="Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
        )

    def _post(self, token: str) -> Any:
        return self.client.post(
            "/api/revoke_leaked_key",
            data=json.dumps({"token": token}),
            content_type="application/json",
        )

    @parameterized.expand(
        [
            ("personal_api_key", CANONICAL_PERSONAL_API_KEY),
            ("legacy_personal_api_key", CANONICAL_PERSONAL_API_KEY),
            ("project_secret_api_key", CANONICAL_PROJECT_SECRET_API_KEY),
            ("oauth_access_token", CANONICAL_OAUTH_ACCESS_TOKEN),
            ("oauth_refresh_token", CANONICAL_OAUTH_REFRESH_TOKEN),
        ]
    )
    @patch("posthog.api.project_secret_api_key.send_project_secret_api_key_exposed")
    @patch("posthog.api.secret_revocation.send_oauth_token_exposed")
    @patch("posthog.api.secret_revocation.send_personal_api_key_exposed")
    def test_auto_detects_and_revokes_each_key_type(
        self,
        kind: str,
        expected_type: str,
        mock_send_personal_api_key_exposed: MagicMock,
        mock_send_oauth_token_exposed: MagicMock,
        mock_send_project_secret_api_key_exposed: MagicMock,
    ) -> None:
        if kind == "personal_api_key":
            token = generate_random_token_personal()
            key = PersonalAPIKey.objects.create(
                user=self.user,
                label="leaked",
                secure_value=hash_key_value(token),
                mask_value=mask_key_value(token),
                scopes=["*"],
            )

            def still_present() -> bool:
                return find_personal_api_key(token) is not None

            def assert_owner_notified() -> None:
                mock_send_personal_api_key_exposed.assert_called_once_with(
                    self.user.id, key.id, mask_key_value(token), PUBLIC_REPORT_MORE_INFO
                )
        elif kind == "legacy_personal_api_key":
            # Keys issued before the phx_ prefix are bare secrets.token_urlsafe(32) output
            # stored under the legacy PBKDF2 hash. They still authenticate, so they must
            # still be revocable here.
            token = secrets.token_urlsafe(32)
            key = PersonalAPIKey.objects.create(
                user=self.user,
                label="leaked legacy",
                secure_value=hash_key_value(
                    token, mode="pbkdf2", legacy_salt=LEGACY_PERSONAL_API_KEY_SALT, iterations=260000
                ),
                mask_value=mask_key_value(token),
                scopes=["*"],
            )

            def still_present() -> bool:
                return find_personal_api_key(token) is not None

            def assert_owner_notified() -> None:
                mock_send_personal_api_key_exposed.assert_called_once_with(
                    self.user.id, key.id, mask_key_value(token), PUBLIC_REPORT_MORE_INFO
                )
        elif kind == "project_secret_api_key":
            project_secret_api_key, token = create_project_secret_api_key(team=self.team, created_by=self.user)

            def still_present() -> bool:
                return find_project_secret_api_key(token) is not None

            def assert_owner_notified() -> None:
                mock_send_project_secret_api_key_exposed.assert_called_once_with(
                    self.team.id, project_secret_api_key.id, mask_key_value(token), PUBLIC_REPORT_MORE_INFO
                )
        elif kind == "oauth_access_token":
            oauth_app = self._create_oauth_app()
            token = "pha_test_leaked_access_token"
            OAuthAccessToken.objects.create(
                user=self.user,
                application=oauth_app,
                token=token,
                expires=timezone.now() + timedelta(hours=1),
                scope="openid profile",
            )

            def still_present() -> bool:
                return find_oauth_access_token(token) is not None

            def assert_owner_notified() -> None:
                mock_send_oauth_token_exposed.assert_called_once_with(
                    self.user.id, "access", mask_key_value(token), PUBLIC_REPORT_MORE_INFO
                )
        else:
            oauth_app = self._create_oauth_app()
            token = "phr_test_leaked_refresh_token"
            OAuthRefreshToken.objects.create(user=self.user, application=oauth_app, token=token)

            def still_present() -> bool:
                return find_oauth_refresh_token(token) is not None

            def assert_owner_notified() -> None:
                mock_send_oauth_token_exposed.assert_called_once_with(
                    self.user.id, "refresh", mask_key_value(token), PUBLIC_REPORT_MORE_INFO
                )

        response = self._post(token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"found": True, "type": expected_type})
        self.assertFalse(still_present())
        assert_owner_notified()

    @parameterized.expand(
        [
            # Recognized prefix, but no such key exists — exercises the one lookup
            # that runs and misses.
            ("known_prefix_but_key_does_not_exist", "phx_this_is_not_a_real_key"),
            # No PostHog key prefix at all — exercises _detect_canonical_type
            # returning None and skipping every lookup entirely.
            ("no_recognized_prefix_at_all", "not-a-posthog-key-at-all"),
            # Matches the legacy unprefixed personal-key shape (43 URL-safe chars), so the
            # personal-key lookup runs and misses. Guards the shape fallback against
            # false positives.
            ("legacy_shape_but_not_a_real_key", "x" * 43),
        ]
    )
    def test_unrecognized_token_is_not_found(self, _name: str, token: str) -> None:
        response = self._post(token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"found": False, "type": None})

    def test_team_secret_token_is_not_auto_detected(self) -> None:
        # Team.secret_api_token shares the "phs_" prefix with project secret API
        # keys, but it's a different model (Team, not ProjectSecretAPIKey), so the
        # single lookup the "phs_" prefix triggers (find_project_secret_api_key)
        # naturally misses — it's intentionally excluded from auto-detect (see
        # _PREFIX_TO_CANONICAL_TYPE in secret_revocation.py) since it can't be
        # auto-rotated without a user to attribute the rotation to.
        token = "phs_legacy_team_secret_token_for_public_endpoint_test"
        self.team.secret_api_token = token
        self.team.save()

        response = self._post(token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"found": False, "type": None})

        self.team.refresh_from_db()
        self.assertEqual(self.team.secret_api_token, token)

    def test_expired_oauth_access_token_still_revokes_the_paired_refresh_token(self) -> None:
        # An expired access token can't authenticate on its own, but revoking still
        # matters: if the same exposure also affects the longer-lived paired refresh
        # token (up to 30 days), that's the only way to close it. Gating this on
        # expiry wouldn't close any capability either way - this endpoint and
        # github.py's webhook are both triggerable by anyone holding a copy of a
        # token, dead or alive (a public GitHub commit gets scanned and reported the
        # same as an anonymous POST here) - so there's no less-exposed path to prefer.
        oauth_app = self._create_oauth_app()
        expired_token = "pha_expired_leaked_access_token"
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=oauth_app,
            token=expired_token,
            expires=timezone.now() - timedelta(hours=1),
            scope="openid profile",
        )
        refresh_token = OAuthRefreshToken.objects.create(
            user=self.user,
            application=oauth_app,
            token="phr_session_paired_with_expired_access",
            access_token=access_token,
        )

        response = self._post(expired_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"found": True, "type": CANONICAL_OAUTH_ACCESS_TOKEN})
        self.assertFalse(OAuthAccessToken.objects.filter(id=access_token.id).exists())
        refresh_token.refresh_from_db()
        self.assertIsNotNone(refresh_token.revoked)

    def test_oauth_access_token_revocation_does_not_touch_other_sessions_with_same_app(self) -> None:
        # A leaked token is evidence about that one token, not the user's other sessions
        # with the same app (e.g. the same app authorized from a second device) - a
        # report about one session must not revoke another.
        oauth_app = self._create_oauth_app()

        leaked_refresh_token = OAuthRefreshToken.objects.create(
            user=self.user, application=oauth_app, token="phr_leaked_session_refresh"
        )
        leaked_access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=oauth_app,
            token="pha_leaked_session_access",
            expires=timezone.now() + timedelta(hours=1),
            scope="openid profile",
            source_refresh_token=leaked_refresh_token,
        )

        other_refresh_token = OAuthRefreshToken.objects.create(
            user=self.user, application=oauth_app, token="phr_other_session_refresh"
        )
        other_access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=oauth_app,
            token="pha_other_session_access",
            expires=timezone.now() + timedelta(hours=1),
            scope="openid profile",
            source_refresh_token=other_refresh_token,
        )

        response = self._post("pha_leaked_session_access")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"found": True, "type": CANONICAL_OAUTH_ACCESS_TOKEN})
        self.assertFalse(OAuthAccessToken.objects.filter(id=leaked_access_token.id).exists())
        leaked_refresh_token.refresh_from_db()
        self.assertIsNotNone(leaked_refresh_token.revoked)

        self.assertTrue(OAuthAccessToken.objects.filter(id=other_access_token.id).exists())
        other_refresh_token.refresh_from_db()
        self.assertIsNone(other_refresh_token.revoked)

    def test_leaked_non_rotating_refresh_token_revokes_every_derived_access_token(self) -> None:
        # DCR/CIMD clients get non-rotating refreshes: every refresh inserts a new access
        # token row with no link back to the refresh token that minted it, instead of
        # updating one row in place. Reporting the refresh token must still catch every
        # access token it could have produced, not just whichever one (if any) happens to
        # still be linked.
        dcr_app = OAuthApplication.objects.create(
            name="Test DCR App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            organization=self.organization,
            user=self.user,
            is_dcr_client=True,
        )
        leaked_refresh_token = OAuthRefreshToken.objects.create(
            user=self.user, application=dcr_app, token="phr_dcr_refresh_token"
        )
        first_access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=dcr_app,
            token="pha_dcr_access_token_1",
            expires=timezone.now() + timedelta(hours=1),
            scope="openid profile",
        )
        second_access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=dcr_app,
            token="pha_dcr_access_token_2",
            expires=timezone.now() + timedelta(hours=1),
            scope="openid profile",
        )

        response = self._post("phr_dcr_refresh_token")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"found": True, "type": CANONICAL_OAUTH_REFRESH_TOKEN})
        self.assertFalse(OAuthRefreshToken.objects.filter(pk=leaked_refresh_token.pk).exists())
        self.assertFalse(OAuthAccessToken.objects.filter(id=first_access_token.id).exists())
        self.assertFalse(OAuthAccessToken.objects.filter(id=second_access_token.id).exists())

    @patch("posthog.api.secret_revocation.send_personal_api_key_exposed")
    @patch("posthog.api.leaked_key.posthoganalytics.capture")
    def test_analytics_capture_includes_token_hash_only_when_found(
        self, mock_capture: MagicMock, mock_send_personal_api_key_exposed: MagicMock
    ) -> None:
        # A real PostHog key is high-entropy, so hashing it is safe to persist. An
        # unrecognized string might be a low-entropy third-party secret pasted by
        # mistake (a password, a short token) - an unsalted SHA-256 of that is
        # dictionary/rainbow-table reversible, so it must not be persisted.
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="leaked",
            secure_value=hash_key_value(token),
            mask_value=mask_key_value(token),
            scopes=["*"],
        )

        self._post(token)
        found_properties = mock_capture.call_args.kwargs["properties"]
        self.assertTrue(found_properties["found"])
        self.assertIn("token_sha256", found_properties)

        mock_capture.reset_mock()

        self._post("not-a-posthog-key-at-all")
        not_found_properties = mock_capture.call_args.kwargs["properties"]
        self.assertFalse(not_found_properties["found"])
        self.assertNotIn("token_sha256", not_found_properties)

    def test_blank_token_returns_400(self) -> None:
        response = self._post("")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_repeated_reports_from_one_ip_are_throttled(self) -> None:
        with patch.object(LeakedKeyReportThrottle, "rate", "1/minute"):
            first = self._post("phx_not_a_real_key")
            second = self._post("phx_not_a_real_key")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
