import json
import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus, urlencode

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from rest_framework import status

from posthog.api.oauth.client_assertion import CLIENT_ASSERTION_TYPE_JWT_BEARER
from posthog.api.oauth.device import DEVICE_CODE_GRANT_TYPE
from posthog.models import Organization, Team
from posthog.models.oauth import (
    OAuthAccessToken,
    OAuthApplication,
    OAuthDeviceGrant,
    OAuthRefreshToken,
    revoke_oauth_session,
)

FORM = "application/x-www-form-urlencoded"
START = "2026-03-02 10:00:00"


class TestOAuthDeviceGrant(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.device_app = OAuthApplication.objects.create(
            name="hog",
            client_id="hog-device-client",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_DEVICE_CODE,
            is_verified=True,
            redirect_uris="",
            algorithm="RS256",
        )

    def _start(self, client_id: str = "hog-device-client", **extra: str) -> dict:
        body = {"client_id": client_id, "scope": "insight:read feature_flag:write llm_gateway:read", **extra}
        response = self.client.post("/oauth/device-authorization/", urlencode(body), content_type=FORM)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response["Cache-Control"], "no-store")
        return response.json()

    def _poll(self, device_code: str, client_id: str = "hog-device-client", **extra: str):
        body = {"grant_type": DEVICE_CODE_GRANT_TYPE, "device_code": device_code, "client_id": client_id, **extra}
        return self.client.post("/oauth/token/", urlencode(body), content_type=FORM)

    def _approve(self, user_code: str, project_id: int | None = None):
        return self.client.post(
            "/api/oauth_device/approve/", {"user_code": user_code, "project_id": project_id or self.team.id}
        )

    @patch("posthog.api.oauth.device.posthoganalytics.capture")
    def test_a_person_approves_and_the_client_gets_a_project_token_once(self, capture) -> None:
        with time_machine.travel(START, tick=False) as clock:
            started = self._start()
            self.assertTrue(started["verification_uri"].endswith("/device"))
            self.assertTrue(started["verification_uri_complete"].endswith(f"/device?code={started['user_code']}"))

            lookup = self.client.post("/api/oauth_device/lookup/", {"user_code": started["user_code"].lower()})
            self.assertEqual(lookup.status_code, status.HTTP_200_OK)
            # A scope outside the ceiling, like the gateway one, never reaches the page.
            self.assertEqual(lookup.json()["scopes"], ["feature_flag:write", "insight:read"])
            self.assertEqual(lookup.json()["client_name"], "hog")

            self.assertEqual(self._approve(started["user_code"]).json(), {"status": "authorized"})
            self.assertEqual(
                [call.kwargs["event"] for call in capture.call_args_list],
                ["oauth_device_authorization_viewed", "oauth_device_authorization_approved"],
            )

            clock.shift(timedelta(seconds=6))
            # The scope sent with the poll doesn't count: the token gets what the person approved.
            token = self._poll(started["device_code"], scope="dashboard:write insight:read")

            self.assertEqual(token.status_code, status.HTTP_200_OK, token.content)
            body = token.json()
            self.assertEqual(body["scoped_teams"], [self.team.id])
            self.assertEqual(sorted(body["scope"].split()), ["feature_flag:write", "insight:read"])
            self.assertTrue(body["refresh_token"])
            access_token = OAuthAccessToken.objects.get(token=body["access_token"])
            self.assertEqual(access_token.user, self.user)
            self.assertEqual(access_token.scoped_teams, [self.team.id])

            clock.shift(timedelta(seconds=6))
            self.assertEqual(self._poll(started["device_code"]).json()["error"], "invalid_grant")

    @parameterized.expand(
        [
            ("a live token", 1, None, ["insight:read", "openid"]),
            ("an expired token with a live refresh token", -1, False, ["insight:read", "openid"]),
            ("an expired token whose refresh token was revoked", -1, True, []),
        ]
    )
    @time_machine.travel(START, tick=False)
    def test_lookup_lists_the_scopes_the_person_already_granted(
        self, _name: str, expires_in_hours: int, refresh_revoked: bool | None, expected: list[str]
    ) -> None:
        access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.device_app,
            token="existing-token",
            scope="openid insight:read",
            expires=timezone.now() + timedelta(hours=expires_in_hours),
            scoped_teams=[self.team.id],
        )
        if refresh_revoked is not None:
            OAuthRefreshToken.objects.create(
                user=self.user,
                application=self.device_app,
                token="existing-refresh",
                access_token=access_token,
                revoked=timezone.now() if refresh_revoked else None,
            )
        started = self._start()

        lookup = self.client.post("/api/oauth_device/lookup/", {"user_code": started["user_code"]})

        # Scopes are listed per project, because a grant in one project grants nothing in another.
        self.assertEqual(
            lookup.json()["granted_scopes"],
            [{"project_id": self.team.id, "organization_id": None, "scopes": expected}] if expected else [],
        )

    @parameterized.expand(
        [
            ("pending", 6, None, "authorization_pending", False),
            ("polled too fast", 1, None, "slow_down", False),
            ("denied", 6, "deny", "access_denied", True),
            ("expired while pending", 3600, None, "expired_token", True),
            ("expired after approval", 3600, "approve", "expired_token", True),
        ]
    )
    @patch("posthog.api.oauth.views.posthoganalytics.capture")
    def test_a_poll_reports_the_grant_state(
        self, _name: str, wait_seconds: int, decision: str | None, expected: str, counts_as_rejected: bool, capture
    ) -> None:
        with time_machine.travel(START, tick=False) as clock:
            started = self._start()
            if decision == "approve":
                self._approve(started["user_code"])
            elif decision == "deny":
                self.client.post("/api/oauth_device/deny/", {"user_code": started["user_code"]})

            clock.shift(timedelta(seconds=wait_seconds))
            response = self._poll(started["device_code"])

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.json()["error"], expected)
            rejected = [call for call in capture.call_args_list if call.kwargs.get("event") == "oauth_token_rejected"]
            self.assertEqual(len(rejected), 1 if counts_as_rejected else 0)

    def test_a_client_that_polls_too_fast_must_wait_longer(self) -> None:
        with time_machine.travel(START, tick=False) as clock:
            started = self._start()
            clock.shift(timedelta(seconds=1))

            too_fast = self._poll(started["device_code"])
            same_second = self._poll(started["device_code"])
            clock.shift(timedelta(seconds=10))
            on_time = self._poll(started["device_code"])

        self.assertEqual(too_fast.json()["error"], "slow_down")
        self.assertEqual(same_second.json()["error"], "slow_down")
        self.assertEqual(OAuthDeviceGrant.objects.get().interval, 10)
        self.assertEqual(on_time.json()["error"], "authorization_pending")

    @parameterized.expand(
        [
            ("an unknown device code", {"device_code": "not-a-real-code"}, "invalid_grant"),
            ("no device code", {"device_code": ""}, "invalid_request"),
        ]
    )
    def test_a_poll_with_a_bad_device_code_fails(self, _name: str, overrides: dict, expected: str) -> None:
        body = {"grant_type": DEVICE_CODE_GRANT_TYPE, "client_id": "hog-device-client", **overrides}
        response = self.client.post("/oauth/token/", urlencode(body), content_type=FORM)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], expected)

    def test_only_the_client_that_started_the_grant_can_redeem_it(self) -> None:
        OAuthApplication.objects.create(
            name="other",
            client_id="other-device-client",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_DEVICE_CODE,
            is_verified=True,
            redirect_uris="",
            algorithm="RS256",
        )
        with time_machine.travel(START, tick=False) as clock:
            started = self._start()
            clock.shift(timedelta(seconds=6))
            # Before approval, another client learns nothing about the grant.
            self.assertEqual(
                self._poll(started["device_code"], client_id="other-device-client").json()["error"], "invalid_grant"
            )
            self._approve(started["user_code"])
            clock.shift(timedelta(seconds=6))

            stolen = self._poll(started["device_code"], client_id="other-device-client")

            self.assertEqual(stolen.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(stolen.json()["error"], "invalid_grant")
            clock.shift(timedelta(seconds=6))
            self.assertEqual(self._poll(started["device_code"]).status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("registered for authorization code", OAuthApplication.GRANT_AUTHORIZATION_CODE, True, "can't use"),
            ("PostHog hasn't verified", OAuthApplication.GRANT_DEVICE_CODE, False, "hasn't verified"),
        ]
    )
    def test_a_client_cannot_start_a_device_grant_when(
        self, _name: str, grant_type: str, is_verified: bool, description: str
    ) -> None:
        OAuthApplication.objects.create(
            name="other app",
            client_id="other-client",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=grant_type,
            is_verified=is_verified,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )
        response = self.client.post(
            "/oauth/device-authorization/", urlencode({"client_id": "other-client"}), content_type=FORM
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "unauthorized_client")
        self.assertIn(description, response.json()["error_description"])
        self.assertFalse(OAuthDeviceGrant.objects.exists())

    def test_a_client_that_loses_its_verification_stops_working(self) -> None:
        with time_machine.travel(START, tick=False) as clock:
            approved = self._start()
            self._approve(approved["user_code"])
            pending = self._start()
            OAuthApplication.objects.filter(pk=self.device_app.pk).update(is_verified=False)
            clock.shift(timedelta(seconds=6))

            redeem = self._poll(approved["device_code"])
            lookup = self.client.post("/api/oauth_device/lookup/", {"user_code": pending["user_code"]})
            approve = self._approve(pending["user_code"])

        self.assertEqual(redeem.json()["error"], "unauthorized_client")
        self.assertFalse(OAuthAccessToken.objects.exists())
        self.assertEqual(lookup.json()["error"], "unverified_client")
        self.assertEqual(approve.json()["error"], "unverified_client")
        self.assertEqual(
            OAuthDeviceGrant.objects.get(device_code=pending["device_code"]).status,
            OAuthDeviceGrant.AUTHORIZATION_PENDING,
        )

    def test_a_confidential_client_must_authenticate_even_when_it_names_the_device_grant(self) -> None:
        OAuthApplication.objects.create(
            name="confidential device client",
            client_id="confidential-device-client",
            client_secret="the-secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_DEVICE_CODE,
            is_verified=True,
            redirect_uris="",
            algorithm="RS256",
        )
        response = self.client.post(
            "/oauth/device-authorization/",
            urlencode({"client_id": "confidential-device-client", "grant_type": DEVICE_CODE_GRANT_TYPE}),
            content_type=FORM,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()["error"], "invalid_client")

    def test_a_confidential_client_logs_in_with_basic_auth(self) -> None:
        client_id = "https://cli.example.com/oauth/client.json"
        OAuthApplication.objects.create(
            name="confidential device client",
            client_id=client_id,
            client_secret="the-secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_DEVICE_CODE,
            is_verified=True,
            redirect_uris="",
            algorithm="RS256",
        )
        # The client names itself only in Basic auth, which form-encodes the client_id (RFC 6749 section 2.3.1).
        basic = "Basic " + base64.b64encode(f"{quote_plus(client_id)}:the-secret".encode()).decode()

        with time_machine.travel(START, tick=False) as clock:
            started = self.client.post(
                "/oauth/device-authorization/",
                urlencode({"scope": "insight:read"}),
                content_type=FORM,
                HTTP_AUTHORIZATION=basic,
            )
            self.assertEqual(started.status_code, status.HTTP_200_OK, started.content)
            self._approve(started.json()["user_code"])
            clock.shift(timedelta(seconds=6))
            token = self.client.post(
                "/oauth/token/",
                urlencode({"grant_type": DEVICE_CODE_GRANT_TYPE, "device_code": started.json()["device_code"]}),
                content_type=FORM,
                HTTP_AUTHORIZATION=basic,
            )

        self.assertEqual(token.status_code, status.HTTP_200_OK, token.content)

    def test_a_private_key_jwt_client_logs_in(self) -> None:
        client_id = "signing-device-client"
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        OAuthApplication.objects.create(
            name="signing device client",
            client_id=client_id,
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_DEVICE_CODE,
            is_verified=True,
            redirect_uris="",
            algorithm="RS256",
            jwks_uri="https://cli.example.com/.well-known/jwks.json",
        )
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
        jwk.update({"kid": "device-key-1", "use": "sig", "alg": "RS256"})

        def assertion(jti: str) -> dict[str, str]:
            # START, the frozen time the token endpoint checks the assertion against.
            now = int(datetime(2026, 3, 2, 10, tzinfo=UTC).timestamp())
            claims = {"iss": client_id, "sub": client_id, "aud": "http://testserver/oauth/token/", "jti": jti}
            token = jwt.encode(
                {**claims, "iat": now, "exp": now + 60}, private_key, algorithm="RS256", headers={"kid": "device-key-1"}
            )
            return {"client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER, "client_assertion": token}

        with (
            time_machine.travel(START, tick=False) as clock,
            override_settings(SITE_URL="http://testserver"),
            patch(
                "posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=({"keys": [jwk]}, None)
            ),
        ):
            started = self.client.post(
                "/oauth/device-authorization/",
                urlencode({"client_id": client_id, "scope": "insight:read", **assertion("start")}),
                content_type=FORM,
            )
            self.assertEqual(started.status_code, status.HTTP_200_OK, started.content)
            self._approve(started.json()["user_code"])
            clock.shift(timedelta(seconds=6))
            token = self._poll(started.json()["device_code"], client_id=client_id, **assertion("poll"))

        self.assertEqual(token.status_code, status.HTTP_200_OK, token.content)

    def test_a_forged_assertion_cannot_claim_it_was_verified(self) -> None:
        OAuthApplication.objects.create(
            name="signing device client",
            client_id="signing-device-client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_DEVICE_CODE,
            is_verified=True,
            redirect_uris="",
            algorithm="RS256",
            jwks_uri="https://cli.example.com/.well-known/jwks.json",
        )
        forged = jwt.encode(
            {"iss": "signing-device-client", "sub": "signing-device-client", "jti": "forged"},
            rsa.generate_private_key(public_exponent=65537, key_size=2048),
            algorithm="RS256",
        )
        body = {
            "client_id": "signing-device-client",
            "client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER,
            "client_assertion": forged,
            # oauthlib answers a missing request attribute from the parameters, so a caller can send this.
            "verified_client_assertion": forged,
        }

        with patch("posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=({"keys": []}, None)):
            response = self.client.post("/oauth/device-authorization/", urlencode(body), content_type=FORM)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, response.content)
        self.assertFalse(OAuthDeviceGrant.objects.exists())

    def test_approval_needs_access_to_the_project(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Elsewhere"), name="Theirs")
        started = self._start()

        response = self._approve(started["user_code"], project_id=other_team.id)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(OAuthDeviceGrant.objects.get().status, OAuthDeviceGrant.AUTHORIZATION_PENDING)

    @parameterized.expand(
        [
            ("2FA", {"enforce_2fa": True}, "two_factor_required"),
            ("verified email domains", {"enforce_verified_domains": True}, "verified_domain_required"),
        ]
    )
    def test_approval_follows_the_policy_of_the_projects_organization(
        self, _name: str, policy: dict, error: str
    ) -> None:
        strict = Organization.objects.create(name="Strict", **policy)
        strict_team = Team.objects.create(organization=strict, name="Strict project")
        self.user.join(organization=strict)
        self.user.current_organization = self.organization
        self.user.save()
        session = self.client.session
        session[settings.SESSION_COOKIE_CREATED_AT_KEY] = 1_800_000_000
        session.save()
        started = self._start()

        response = self._approve(started["user_code"], project_id=strict_team.id)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self.assertEqual(response.json()["error"], error)
        self.assertEqual(OAuthDeviceGrant.objects.get().status, OAuthDeviceGrant.AUTHORIZATION_PENDING)

    @parameterized.expand(
        [
            ("a wrong code", "BCDF-GHJK"),
            ("an expired code", None),
        ]
    )
    @time_machine.travel(START, tick=False)
    def test_approval_refuses(self, _name: str, user_code: str | None) -> None:
        started = self._start()
        if user_code is None:
            OAuthDeviceGrant.objects.update(expires=timezone.now() - timedelta(seconds=1))

        response = self._approve(user_code or started["user_code"])

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "invalid_code")

    def test_a_personal_api_key_cannot_approve_a_device(self) -> None:
        started = self._start()
        self.client.logout()
        key = self.create_personal_api_key_with_scopes(["*"])

        response = self.client.post(
            "/api/oauth_device/approve/",
            {"user_code": started["user_code"], "project_id": self.team.id},
            headers={"authorization": f"Bearer {key}"},
        )

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(OAuthDeviceGrant.objects.get().status, OAuthDeviceGrant.AUTHORIZATION_PENDING)

    def test_entering_codes_is_throttled(self) -> None:
        responses = [
            self.client.post("/api/oauth_device/lookup/", {"user_code": "BCDF-GHJK"}).status_code for _ in range(11)
        ]

        self.assertEqual(responses[:10], [status.HTTP_400_BAD_REQUEST] * 10)
        self.assertEqual(responses[10], status.HTTP_429_TOO_MANY_REQUESTS)

    @parameterized.expand([("in the body", False, "invalid_client"), ("in the query string", True, "invalid_request")])
    def test_a_new_cimd_client_gets_the_cimd_rate_limit(self, _name: str, in_query: bool, expected: str) -> None:
        client_id = urlencode({"client_id": "https://new-client.example.com/.well-known/oauth-client-metadata.json"})
        throttle = MagicMock(allow_request=MagicMock(return_value=False), wait=MagicMock(return_value=30))
        with (
            patch("posthog.api.oauth.views.CIMD_THROTTLE_CLASSES", new=[MagicMock(return_value=throttle)]),
            patch("posthog.api.oauth.cimd.requests.Session.get") as fetch,
        ):
            if in_query:
                response = self.client.post(f"/oauth/device-authorization/?{client_id}", "", content_type=FORM)
            else:
                response = self.client.post("/oauth/device-authorization/", client_id, content_type=FORM)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], expected)
        fetch.assert_not_called()

    def test_a_device_grant_always_asks_for_the_scopes_the_client_requires(self) -> None:
        OAuthApplication.objects.create(
            name="required",
            client_id="required-scopes-client",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_DEVICE_CODE,
            is_verified=True,
            redirect_uris="",
            algorithm="RS256",
            scopes=["insight:read"],
            optional_scopes=["dashboard:write"],
        )
        started = self._start(client_id="required-scopes-client", scope="dashboard:write")

        lookup = self.client.post("/api/oauth_device/lookup/", {"user_code": started["user_code"]})

        self.assertEqual(lookup.json()["scopes"], ["dashboard:write", "insight:read"])

    def test_disconnecting_the_app_drops_an_approved_device_grant_the_client_has_not_redeemed(self) -> None:
        with time_machine.travel(START, tick=False) as clock:
            started = self._start()
            self._approve(started["user_code"])
            existing = OAuthAccessToken.objects.create(
                user=self.user,
                application=self.device_app,
                token="pha_existing",
                expires=timezone.now() + timedelta(hours=1),
                scoped_teams=[self.team.id],
            )

            revoke_oauth_session(access_token=existing)
            clock.shift(timedelta(seconds=6))

            self.assertEqual(self._poll(started["device_code"]).json()["error"], "invalid_grant")

    def test_starting_device_grants_is_limited_per_address(self) -> None:
        throttle = MagicMock(allow_request=MagicMock(return_value=False))
        with patch(
            "posthog.api.oauth.device.DEVICE_AUTHORIZATION_THROTTLE_CLASSES", new=(MagicMock(return_value=throttle),)
        ):
            response = self.client.post(
                "/oauth/device-authorization/", urlencode({"client_id": "hog-device-client"}), content_type=FORM
            )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertFalse(OAuthDeviceGrant.objects.exists())
