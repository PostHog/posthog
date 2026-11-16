import time
import base64
import hashlib
from datetime import timedelta
from typing import cast
from urllib.parse import parse_qs, quote, urlparse

import time_machine
from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.api.oauth.ema_issuer import EMA_ISSUER_MANAGE_SCOPE
from posthog.api.oauth.metadata import authorization_server_metadata, protected_resource_metadata
from posthog.constants import AvailableFeature
from posthog.models.identity_provider_config import ConfigScope, DomainScope, IdentityProviderConfig
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthApplicationAccessLevel, OAuthRefreshToken
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions

CLIENT_ID = "ema-test-client"
CLIENT_SECRET = "ema-test-secret"
REDIRECT_URI = "https://client.example.com/callback"
CODE_VERIFIER = "ema-test-code-verifier-0123456789-abcdefghijklmnop"
ISSUER = "https://identity.example.com/issuers/first"
OTHER_ISSUER = "https://identity.example.com/issuers/second"


def _code_challenge() -> str:
    digest = hashlib.sha256(CODE_VERIFIER.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


class TestEmaIssuerScopeIsNotAdvertised(SimpleTestCase):
    def test_scope_is_missing_from_discovery_metadata(self):
        for document in (
            authorization_server_metadata("https://posthog.example.com"),
            protected_resource_metadata("https://posthog.example.com"),
        ):
            self.assertNotIn(EMA_ISSUER_MANAGE_SCOPE, cast(list[str], document["scopes_supported"]))


class TestEmaIssuerSetup(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.XAA_AUTHENTICATION, "name": "XAA Authentication"}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        OrganizationDomain.objects.create(
            organization=self.organization, domain="example.com", verified_at=timezone.now()
        )
        self.application = OAuthApplication.objects.create(
            name="Example agent",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
            hash_client_secret=True,
            algorithm="RS256",
            scopes=["feature_flag:read"],
            can_manage_ema_issuer=True,
        )

    def _authorize_url(self, client_id: str = CLIENT_ID) -> str:
        return (
            f"/oauth/authorize/?client_id={client_id}&redirect_uri={quote(REDIRECT_URI)}&response_type=code"
            f"&scope={quote(EMA_ISSUER_MANAGE_SCOPE)}&code_challenge={_code_challenge()}&code_challenge_method=S256"
        )

    def _consent(self, **overrides) -> dict:
        return {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": _code_challenge(),
            "code_challenge_method": "S256",
            "scope": EMA_ISSUER_MANAGE_SCOPE,
            "allow": True,
            "access_level": OAuthApplicationAccessLevel.ORGANIZATION.value,
            "scoped_organizations": [str(self.organization.id)],
            "scoped_teams": [],
            **overrides,
        }

    def _setup_token(self, *, scope: str = EMA_ISSUER_MANAGE_SCOPE, organization_id=None) -> OAuthAccessToken:
        return OAuthAccessToken.objects.create(
            user=self.user,
            application=self.application,
            token=f"pha_ema_test_{OAuthAccessToken.objects.count()}",
            scope=scope,
            expires=timezone.now() + timedelta(minutes=5),
            scoped_organizations=[str(organization_id or self.organization.id)],
        )

    def _put_issuer(self, token: OAuthAccessToken | str, issuer: str = ISSUER):
        value = token if isinstance(token, str) else token.token
        return self.client.put(
            "/oauth/ema/trusted-issuer/",
            data={"ema_issuer": issuer},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

    def test_admin_registers_issuer_from_consent_to_setup_call(self):
        consent_screen = self.client.get(self._authorize_url())
        self.assertEqual(consent_screen.status_code, status.HTTP_200_OK)
        consent_context = consent_screen.context["posthog_app_context"]["oauth_ema_issuer_consent"]
        self.assertEqual(
            consent_context["organizations"],
            [
                {
                    "id": str(self.organization.id),
                    "name": self.organization.name,
                    "verified_domains": ["example.com"],
                    "disabled_reason": None,
                }
            ],
        )

        approval = self.client.post("/oauth/authorize/", self._consent(), format="json")
        self.assertEqual(approval.status_code, status.HTTP_200_OK, approval.json())
        code = parse_qs(urlparse(approval.json()["redirect_to"]).query)["code"][0]

        token_response = self.client.post(
            "/oauth/token/",
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": CODE_VERIFIER,
            },
        )
        self.assertEqual(token_response.status_code, status.HTTP_200_OK, token_response.json())
        token_body = token_response.json()
        self.assertEqual(token_body["scope"], EMA_ISSUER_MANAGE_SCOPE)
        self.assertEqual(token_body["expires_in"], 300)
        self.assertNotIn("refresh_token", token_body)
        self.assertEqual(token_body["ema_setup_endpoint"], f"{settings.SITE_URL.rstrip('/')}/oauth/ema/trusted-issuer/")
        self.assertFalse(OAuthRefreshToken.objects.filter(application=self.application).exists())

        setup = self._put_issuer(token_body["access_token"])

        self.assertEqual(setup.status_code, status.HTTP_200_OK, setup.json())
        self.assertEqual(setup.json(), {"aud_tenant": str(self.organization.id)})
        config = IdentityProviderConfig.objects.get(organization=self.organization)
        self.assertEqual(
            (
                config.config_scope,
                config.domain_scope,
                config.id_jag_issuer_url,
                config.id_jag_allowed_clients,
                config.id_jag_registered_by_application_id,
            ),
            (ConfigScope.ID_JAG, DomainScope.ALL, ISSUER, [], self.application.id),
        )

        reused = self._put_issuer(token_body["access_token"], OTHER_ISSUER)
        self.assertEqual(reused.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(reused.json()["error"], "invalid_token")

    def test_client_without_the_flag_gets_invalid_scope(self):
        other = OAuthApplication.objects.create(
            name="Other agent",
            client_id="other-client",
            client_secret=CLIENT_SECRET,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=REDIRECT_URI,
            algorithm="RS256",
            is_first_party=True,
        )

        response = self.client.get(self._authorize_url(client_id=other.client_id))

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(parse_qs(urlparse(response["Location"]).query)["error"], ["invalid_scope"])

    @parameterized.expand(
        [
            ("member_not_admin", "member", status.HTTP_403_FORBIDDEN, "access_denied"),
            ("plan_without_xaa", "no_feature", status.HTTP_403_FORBIDDEN, "access_denied"),
            ("no_verified_domain", "no_domain", status.HTTP_403_FORBIDDEN, "access_denied"),
            ("all_organizations", "all_access", status.HTTP_400_BAD_REQUEST, "invalid_request"),
        ]
    )
    def test_consent_is_refused(self, _name, case, expected_status, expected_error):
        overrides: dict = {}
        if case == "member":
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
        elif case == "no_feature":
            self.organization.available_product_features = []
            self.organization.save()
        elif case == "no_domain":
            OrganizationDomain.objects.filter(organization=self.organization).update(verified_at=None)
        elif case == "all_access":
            overrides = {"access_level": OAuthApplicationAccessLevel.ALL.value, "scoped_organizations": []}

        response = self.client.post("/oauth/authorize/", self._consent(**overrides), format="json")

        self.assertEqual(response.status_code, expected_status, response.json())
        self.assertEqual(response.json()["error"], expected_error)

    def test_consent_needs_a_recent_sign_in(self):
        with time_machine.travel(timezone.now() + timedelta(seconds=settings.SESSION_SENSITIVE_ACTIONS_AGE + 10)):
            response = self.client.post("/oauth/authorize/", self._consent(), format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())
        self.assertEqual(response.json()["code"], "sensitive_action_required_reauth")

    @parameterized.expand(
        [
            ("issuer_in_another_config_of_the_organization", "taken", status.HTTP_409_CONFLICT, "issuer_in_use"),
            ("demoted_after_consent", "demoted", status.HTTP_403_FORBIDDEN, "access_denied"),
            ("issuer_not_https", "http://identity.example.com/issuers/first", 400, "invalid_request"),
            ("issuer_not_a_url", "https://[invalid", 400, "invalid_request"),
            ("issuer_port_out_of_range", "https://identity.example.com:70000/issuers/first", 400, "invalid_request"),
            ("token_without_scope", "other_scope", status.HTTP_403_FORBIDDEN, "insufficient_scope"),
        ]
    )
    def test_setup_call_is_refused_and_registers_nothing(self, _name, case, expected_status, expected_error):
        issuer = ISSUER
        token = self._setup_token(scope="feature_flag:read" if case == "other_scope" else EMA_ISSUER_MANAGE_SCOPE)
        if case == "taken":
            IdentityProviderConfig.objects.create(organization=self.organization, id_jag_issuer_url=f"{ISSUER}/")
        elif case == "demoted":
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
        elif case.startswith("http"):
            issuer = case

        response = self._put_issuer(token, issuer)

        self.assertEqual(response.status_code, expected_status, response.json())
        self.assertEqual(response.json()["error"], expected_error)
        self.assertFalse(IdentityProviderConfig.objects.filter(id_jag_registered_by_application__isnull=False).exists())
        self.assertTrue(OAuthAccessToken.objects.filter(pk=token.pk).exists())

    @parameterized.expand([("hand_entered", False), ("client_registered", True)])
    def test_issuer_trusted_by_another_organization_does_not_block_setup(self, _name, client_registered):
        IdentityProviderConfig.objects.create(
            organization=Organization.objects.create(name="Other organization"),
            id_jag_issuer_url=ISSUER,
            id_jag_registered_by_application=self.application if client_registered else None,
        )

        response = self._put_issuer(self._setup_token(), ISSUER)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    def _other_admin_organization(self, **fields) -> Organization:
        organization = Organization.objects.create(name="Restricted organization", **fields)
        organization.available_product_features = [
            {"key": AvailableFeature.XAA_AUTHENTICATION, "name": "XAA Authentication"}
        ]
        organization.save()
        OrganizationMembership.objects.create(
            user=self.user, organization=organization, level=OrganizationMembership.Level.ADMIN
        )
        OrganizationDomain.objects.create(
            organization=organization, domain="restricted.example.com", verified_at=timezone.now()
        )
        return organization

    @parameterized.expand(
        [
            ("two_factor", {"enforce_2fa": True}),
            ("verified_email_domains", {"enforce_verified_domains": True}),
        ]
    )
    def test_consent_follows_the_policy_of_the_selected_organization(self, _name, policy):
        organization = self._other_admin_organization(**policy)
        session = self.client.session
        session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time()
        session.save()

        response = self.client.post(
            "/oauth/authorize/", self._consent(scoped_organizations=[str(organization.id)]), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())
        self.assertEqual(response.json()["error"], "access_denied")

    def test_setup_call_respects_the_token_organization_ip_restrictions(self):
        organization = self._other_admin_organization()
        OrganizationIPRestrictions.objects.create(
            organization=organization, enabled=True, ip_restrictions=["192.0.2.0/24"]
        )

        response = self._put_issuer(self._setup_token(organization_id=organization.id))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())
        self.assertEqual(response.json()["error"], "access_denied")
        self.assertFalse(IdentityProviderConfig.objects.filter(organization=organization).exists())

    def test_second_registration_replaces_the_first_issuer(self):
        self.assertEqual(self._put_issuer(self._setup_token(), ISSUER).status_code, status.HTTP_200_OK)
        self.assertEqual(self._put_issuer(self._setup_token(), OTHER_ISSUER).status_code, status.HTTP_200_OK)

        configs = IdentityProviderConfig.objects.filter(organization=self.organization)
        self.assertEqual([config.id_jag_issuer_url for config in configs], [OTHER_ISSUER])
