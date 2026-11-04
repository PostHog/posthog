import hashlib
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.contrib.sessions.backends.db import SessionStore
from django.core.signing import TimestampSigner
from django.utils import timezone

import jwt
from loginas import settings as la_settings
from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.livestream import LivestreamAuthentication
from posthog.api.team.live_events import live_events_token_for_request
from posthog.auth import OAuthAccessTokenAuthentication
from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import OrganizationDomain, OrganizationMembership, PropertyDefinition, User
from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions
from posthog.test.authentication_checks import covers_authentication
from posthog.test.persons import create_group_type_mapping

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel


class TestLivestreamAuthorization(APIBaseTest):
    def _token(self, audience: PosthogJwtAudience = PosthogJwtAudience.LIVESTREAM) -> str:
        return encode_jwt(
            {
                "user_id": self.user.id,
                "team_id": self.team.id,
                "organization_id": str(self.organization.id),
                "api_token": self.team.api_token,
            },
            timedelta(days=7),
            audience,
        )

    @parameterized.expand([("session",), ("oauth",)])
    def test_preserves_verified_staff_impersonation_without_reusing_member_tokens(self, credential: str) -> None:
        staff = User.objects.create_user(
            email="livestream-staff@example.com", first_name="Staff", password="test-password", is_staff=True
        )
        request = Request(APIRequestFactory().get("/api/projects/@current/"))
        request.user = self.user
        request.auth = None
        request.session = SessionStore()
        with patch.object(request, "_authenticator", None, create=True):
            ordinary = live_events_token_for_request(self.team, request)
            assert ordinary is not None
            authenticator = None
            if credential == "session":
                request.session[la_settings.USER_SESSION_FLAG] = TimestampSigner().sign(str(staff.id))
            else:
                authenticator = OAuthAccessTokenAuthentication()
                authenticator.access_token = OAuthAccessToken(user=self.user, impersonated_by=staff, scope="query:read")
            with patch.object(request, "_authenticator", authenticator, create=True):
                impersonated = live_events_token_for_request(self.team, request)
                assert impersonated is not None and impersonated != ordinary
                assert live_events_token_for_request(self.team, request) == impersonated
            request.session.clear()
            assert live_events_token_for_request(self.team, request) == ordinary
        OrganizationIPRestrictions.objects.create(organization=self.organization, ip_restrictions=["203.0.113.0/24"])
        self.client.logout()
        headers = {"Accept": "application/json"}
        ordinary_response = self.client.get(
            "/api/livestream/authorize/", headers={**headers, "Authorization": f"Bearer {ordinary}"}
        )
        assert ordinary_response.status_code == 403
        response = self.client.get(
            "/api/livestream/authorize/", headers={**headers, "Authorization": f"Bearer {impersonated}"}
        )
        assert response.status_code == 200, response.content
        assert response.json()["ip_restrictions"] == []
        if credential == "session":
            staff.is_staff = False
            staff.save(update_fields=["is_staff"])
        else:
            staff.is_active = False
            staff.save(update_fields=["is_active"])
        revoked = self.client.get(
            "/api/livestream/authorize/", headers={**headers, "Authorization": f"Bearer {impersonated}"}
        )
        assert revoked.status_code == 401

    @parameterized.expand(
        [
            ("valid", "1", 200),
            ("old_key", "1", 200),
            ("missing", "1", 403),
            ("wrong_team", "1", 403),
            ("wrong_operation", "1", 403),
            ("wrong_viewer", "1", 403),
            ("wrong_key", "1", 403),
            ("expired", "1", 403),
            ("missing_expiry", "1", 403),
            ("unconfigured", "1", 403),
            ("valid", "", 403),
        ]
    )
    def test_returns_current_normalized_ip_policies_only_to_authenticated_streaming_clients(
        self, proof: str, capability: str, expected_status: int
    ) -> None:
        self.client.logout()
        token = self._token()
        policy = OrganizationIPRestrictions.objects.create(
            organization=self.organization,
            ip_restrictions=["203.0.113.7/255.255.255.0", "2001:db8::7"],
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-PostHog-Livestream-IP-Policy": capability,
        }
        claims = {
            "team_id": self.team.id + 1 if proof == "wrong_team" else self.team.id,
            "operation": "other_operation" if proof == "wrong_operation" else "read_ip_policy",
            "viewer_token_sha256": hashlib.sha256(
                ("different-viewer" if proof == "wrong_viewer" else headers["Authorization"]).encode()
            ).hexdigest(),
        }
        primary_key = "test-livestream-service-primary-key-32-bytes"
        old_key = "test-livestream-service-previous-key-32-bytes"
        key = old_key if proof == "old_key" else primary_key
        if proof == "wrong_key":
            key = "untrusted-livestream-service-key-32-bytes"
        if proof == "missing_expiry":
            headers["X-PostHog-Livestream-Service-Token"] = jwt.encode(
                {**claims, "aud": PosthogJwtAudience.LIVESTREAM_AUTHORIZATION.value}, key, algorithm="HS256"
            )
        elif proof != "missing":
            headers["X-PostHog-Livestream-Service-Token"] = encode_jwt(
                claims,
                timedelta(minutes=-1 if proof == "expired" else 1),
                PosthogJwtAudience.LIVESTREAM_AUTHORIZATION,
                signing_key=key,
            )

        with self.settings(
            LIVESTREAM_AUTHORIZATION_SIGNING_KEYS=[] if proof == "unconfigured" else [primary_key, old_key]
        ):
            response = self.client.get("/api/livestream/authorize/", headers=headers)

            assert response.status_code == expected_status, response.content
            if expected_status == 200:
                assert response.json()["ip_restrictions"] == [["203.0.113.0/24", "2001:db8::7/128"]]
                policy.ip_restrictions = ["198.51.100.0/24"]
                policy.save()
                updated = self.client.get("/api/livestream/authorize/", headers=headers)
                assert updated.status_code == 200
                assert updated.json()["ip_restrictions"] == [["198.51.100.0/24"]]

    @parameterized.expand(
        [
            ("membership", 403),
            ("project_access", 403),
            ("user", 401),
            ("project_token", 401),
            ("inactive_organization", 403),
            ("organization_with_unknown_active_state", 403),
            ("organization_pending_deletion", 403),
            ("unverified_email_domain", 403),
        ]
    )
    def test_rechecks_current_access(self, revoked: str, expected_status: int) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        authorization = f"Bearer {self._token()}"
        initial = self.client.get(
            "/api/livestream/authorize/", HTTP_AUTHORIZATION=authorization, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial["Cache-Control"], "no-store")
        self.assertEqual(
            initial.json(),
            {
                "ip_restrictions": [],
                "restricted_event_properties": [],
                "restricted_person_properties": [],
                "restricted_group_properties": {},
            },
        )
        legacy = self.client.get("/api/livestream/authorize/", HTTP_AUTHORIZATION=authorization)
        self.assertEqual(legacy.status_code, 204)
        self.assertEqual(legacy["Cache-Control"], "no-store")

        if revoked == "membership":
            self.organization_membership.delete()
        elif revoked == "project_access":
            AccessControl.objects.create(
                team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
            )
        elif revoked == "user":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        elif revoked == "project_token":
            self.team.api_token = "test-rotated-project-token"
            self.team.save(update_fields=["api_token"])
        elif revoked == "inactive_organization":
            self.organization.is_active = False
            self.organization.save(update_fields=["is_active"])
        elif revoked == "organization_with_unknown_active_state":
            self.organization.is_active = None
            self.organization.save(update_fields=["is_active"])
        elif revoked == "organization_pending_deletion":
            self.organization.is_pending_deletion = True
            self.organization.save(update_fields=["is_pending_deletion"])
        else:
            OrganizationDomain.objects.create(
                domain="example.com", organization=self.organization, verified_at=timezone.now()
            )
            self.organization.enforce_verified_domains = True
            self.organization.save(update_fields=["enforce_verified_domains"])

        self.assertEqual(
            self.client.get("/api/livestream/authorize/", HTTP_AUTHORIZATION=authorization).status_code, expected_status
        )

    @parameterized.expand([(None,), (PosthogJwtAudience.IMPERSONATED_USER,)])
    def test_rejects_other_authentication(self, audience: PosthogJwtAudience | None) -> None:
        authorization = f"Bearer {self._token(audience)}" if audience else ""
        self.assertEqual(
            self.client.get("/api/livestream/authorize/", HTTP_AUTHORIZATION=authorization).status_code, 401
        )

    @covers_authentication(LivestreamAuthentication)
    def test_lists_the_properties_hidden_from_the_user(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        create_group_type_mapping(
            team=self.team, project=self.team.project, group_type="organization", group_type_index=0
        )
        for name, property_type, group_type_index in (
            ("$ip", PropertyDefinition.Type.EVENT, None),
            ("email", PropertyDefinition.Type.PERSON, None),
            ("$browser", PropertyDefinition.Type.EVENT, None),
            ("email", PropertyDefinition.Type.GROUP, 0),
        ):
            definition = PropertyDefinition.objects.create(
                team=self.team, name=name, type=property_type, group_type_index=group_type_index
            )
            PropertyAccessControl.objects.create(
                team=self.team,
                property_definition=definition,
                access_level=PropertyAccessLevel.NONE.value if name != "$browser" else PropertyAccessLevel.READ.value,
            )

        response = self.client.get(
            "/api/livestream/authorize/", HTTP_AUTHORIZATION=f"Bearer {self._token()}", HTTP_ACCEPT="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ip_restrictions": [],
                "restricted_event_properties": ["$ip"],
                "restricted_person_properties": ["email"],
                "restricted_group_properties": {"organization": ["email"]},
            },
        )

        # When the group types cannot be loaded the rule still applies, to every type.
        with patch("posthog.api.livestream.get_group_types_for_project", return_value=[]):
            response = self.client.get(
                "/api/livestream/authorize/",
                HTTP_AUTHORIZATION=f"Bearer {self._token()}",
                HTTP_ACCEPT="application/json",
            )
        self.assertEqual(response.json()["restricted_group_properties"], {"*": ["email"]})

    def test_refuses_an_account_an_access_rule_blocks(self) -> None:
        with patch("posthog.auth.security_access_refused", return_value=True):
            response = self.client.get("/api/livestream/authorize/", HTTP_AUTHORIZATION=f"Bearer {self._token()}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "access_blocked")
