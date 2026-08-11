import json
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

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
from posthog.models.personal_api_key import find_personal_api_key
from posthog.models.project_secret_api_key import find_project_secret_api_key
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
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

    def _post(self, token: str):
        return self.client.post(
            "/api/alerts/leaked_key",
            data=json.dumps({"token": token}),
            content_type="application/json",
        )

    @parameterized.expand(
        [
            ("personal_api_key", CANONICAL_PERSONAL_API_KEY),
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
        mock_send_personal_api_key_exposed,
        mock_send_oauth_token_exposed,
        mock_send_project_secret_api_key_exposed,
    ) -> None:
        if kind == "personal_api_key":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=self.user,
                label="leaked",
                secure_value=hash_key_value(token),
                mask_value=mask_key_value(token),
                scopes=["*"],
            )

            def still_present() -> bool:
                return find_personal_api_key(token) is not None
        elif kind == "project_secret_api_key":
            _, token = create_project_secret_api_key(team=self.team, created_by=self.user)

            def still_present() -> bool:
                return find_project_secret_api_key(token) is not None
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
        else:
            oauth_app = self._create_oauth_app()
            token = "phr_test_leaked_refresh_token"
            OAuthRefreshToken.objects.create(user=self.user, application=oauth_app, token=token)

            def still_present() -> bool:
                return find_oauth_refresh_token(token) is not None

        response = self._post(token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"found": True, "type": expected_type})
        self.assertFalse(still_present())

    @parameterized.expand(
        [
            # Recognized prefix, but no such key exists — exercises the one lookup
            # that runs and misses.
            ("known_prefix_but_key_does_not_exist", "phx_this_is_not_a_real_key"),
            # No PostHog key prefix at all — exercises _detect_canonical_type
            # returning None and skipping every lookup entirely.
            ("no_recognized_prefix_at_all", "not-a-posthog-key-at-all"),
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

    def test_blank_token_returns_400(self) -> None:
        response = self._post("")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
