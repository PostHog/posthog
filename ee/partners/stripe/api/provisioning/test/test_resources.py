from datetime import timedelta

from unittest.mock import MagicMock, patch

from django.utils import timezone

import requests
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions
from posthog.models.organization_provisioning import OrganizationProvisioning
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.utils import generate_random_oauth_access_token
from posthog.project_creation_limits import (
    ORGANIZATION_PROJECT_LIMIT_MESSAGE,
    PLAN_PROJECT_LIMIT_MESSAGE,
    PROJECT_CREATION_REQUIRES_ADMIN_MESSAGE,
)
from posthog.test.authentication_checks import covers_authentication

from products.access_control.backend.models.access_control import AccessControl

from ee.models.license import License
from ee.partners.stripe.api.provisioning.authentication import StripeBearerAuthentication
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

RESOURCES_URL = f"{BASE_PATH}/provisioning/resources"
GRANTED_SCOPES = ["insight:read", "project:read"]
UNLIMITED_PROJECTS_FEATURE = {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": None}
ONE_PROJECT_FEATURE = {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": 1}
SIX_PROJECTS_FEATURE = {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": 6}
MEMBERS_CAN_CREATE_PROJECTS_FEATURE = {
    "key": AvailableFeature.ORGANIZATION_INVITE_SETTINGS,
    "name": AvailableFeature.ORGANIZATION_INVITE_SETTINGS,
}


class TestResources(StripeProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_create_returns_access_configuration_and_pat(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            RESOURCES_URL, data={"service_id": "analytics", "label_prefix": "Stripe"}, token=token
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "complete"
        assert body["id"] == str(self.team.id)
        assert body["service_id"] == "analytics"
        config = body["complete"]["access_configuration"]
        assert config["api_key"] == self.team.api_token
        assert config["host"]
        assert config["personal_api_key"].startswith("phx_")

        pat = PersonalAPIKey.objects.get(user=self.user)
        assert pat.label == f"Stripe - {self.team.name}"[:40]
        assert pat.scoped_teams == [self.team.id]
        assert pat.provisioned_by_id == self.stripe_app.id

        assert TeamProvisioningConfig.objects.get(team=self.team).service_id == "analytics"

    def test_create_mints_granted_scopes_for_an_app_without_ceiling_or_key_flag(self) -> None:
        self.stripe_app.scopes = []
        self.stripe_app.save(update_fields=["scopes"])
        self.stripe_app.update_provisioning(issues_personal_api_key=False)
        self._seed_auth_code("code_wide", scopes=GRANTED_SCOPES)
        token = self._post_signed(
            f"{BASE_PATH}/oauth/token",
            data={"grant_type": "authorization_code", "code": "code_wide"},
            content_type="application/x-www-form-urlencoded",
        ).json()["access_token"]

        res = self._post_signed_with_bearer(RESOURCES_URL, data={"service_id": "analytics"}, token=token)

        assert res.status_code == 200
        assert res.json()["complete"]["access_configuration"]["personal_api_key"].startswith("phx_")
        pat = PersonalAPIKey.objects.get(user=self.user, provisioned_by=self.stripe_app)
        assert sorted(pat.scopes) == sorted(GRANTED_SCOPES)

    def test_create_with_project_id_is_idempotent(self):
        self.organization.available_product_features = [UNLIMITED_PROJECTS_FEATURE]
        self.organization.save()
        token = self._get_bearer_token()
        first = self._post_signed_with_bearer(RESOURCES_URL, data={"project_id": "proj_1"}, token=token)
        assert first.status_code == 200
        second = self._post_signed_with_bearer(RESOURCES_URL, data={"project_id": "proj_1"}, token=token)
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        # A project_id provisions a dedicated team, distinct from the consent team.
        assert first.json()["id"] != str(self.team.id)

    @parameterized.expand(
        [
            ("without_projects_feature", [], None, PLAN_PROJECT_LIMIT_MESSAGE),
            ("at_plan_limit", [ONE_PROJECT_FEATURE], None, PLAN_PROJECT_LIMIT_MESSAGE),
            ("at_organization_maximum", [UNLIMITED_PROJECTS_FEATURE], 1, ORGANIZATION_PROJECT_LIMIT_MESSAGE),
        ]
    )
    def test_create_with_new_project_id_refused_at_project_limit(
        self, _name: str, features: list[dict], organization_maximum: int | None, message: str
    ) -> None:
        self.organization.available_product_features = features
        self.organization.save()
        token = self._get_bearer_token()
        team_count = Team.objects.filter(organization=self.organization).count()

        with patch(
            "posthog.project_creation_limits.MAX_ALLOWED_PROJECTS_PER_ORG",
            organization_maximum or 2000,
        ):
            res = self._post_signed_with_bearer(RESOURCES_URL, data={"project_id": "proj_over_limit"}, token=token)

        assert res.status_code == 403
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "project_limit_reached", "message": message},
        }
        assert Team.objects.filter(organization=self.organization).count() == team_count

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, False, None, 403),
            ("member_when_organization_allows_it", OrganizationMembership.Level.MEMBER, True, None, 200),
            (
                "member_of_a_stripe_created_organization",
                OrganizationMembership.Level.MEMBER,
                False,
                OrganizationProvisioning.Partner.STRIPE_PROJECTS,
                403,
            ),
            (
                "member_of_an_organization_another_partner_created",
                OrganizationMembership.Level.MEMBER,
                False,
                OrganizationProvisioning.Partner.VERCEL,
                403,
            ),
            ("admin", OrganizationMembership.Level.ADMIN, False, None, 200),
            ("owner", OrganizationMembership.Level.OWNER, False, None, 200),
        ]
    )
    def test_create_with_new_project_id_follows_project_creation_policy(
        self,
        _name: str,
        level: OrganizationMembership.Level,
        members_can_create_projects: bool,
        created_by: OrganizationProvisioning.Partner | None,
        expected_status: int,
    ) -> None:
        self.organization.available_product_features = [UNLIMITED_PROJECTS_FEATURE, MEMBERS_CAN_CREATE_PROJECTS_FEATURE]
        self.organization.members_can_create_projects = members_can_create_projects
        self.organization.save()
        if created_by is not None:
            OrganizationProvisioning.objects.create(
                organization=self.organization,
                partner=created_by,
                # Vercel provisions without an OAuth application.
                application=self.stripe_app if created_by == OrganizationProvisioning.Partner.STRIPE_PROJECTS else None,
            )
        self.organization_membership.level = level
        self.organization_membership.save()
        token = self._get_bearer_token()
        team_count = Team.objects.filter(organization=self.organization).count()

        res = self._post_signed_with_bearer(RESOURCES_URL, data={"project_id": "proj_policy"}, token=token)

        assert res.status_code == expected_status, res.content
        if expected_status == 403:
            assert res.json()["error"] == {"code": "forbidden", "message": PROJECT_CREATION_REQUIRES_ADMIN_MESSAGE}
            assert Team.objects.filter(organization=self.organization).count() == team_count
        else:
            assert Team.objects.filter(organization=self.organization).count() == team_count + 1

    def test_create_with_new_project_id_refused_by_policy_does_not_activate_billing(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        token = self._get_bearer_token()
        license = License(key="12345::67890")

        with (
            patch("ee.partners.stripe.api.provisioning.billing.get_cached_instance_license", return_value=license),
            patch("ee.partners.stripe.api.provisioning.billing._team_has_active_billing", return_value=False),
            patch("ee.billing.billing_manager.http_session.post") as billing_post,
        ):
            res = self._post_signed_with_bearer(
                RESOURCES_URL,
                data={
                    "project_id": "proj_refused",
                    "payment_credentials": {"type": "stripe_payment_token", "stripe_payment_token": "spt_1"},
                },
                token=token,
            )

        assert res.status_code == 403
        assert res.json()["error"]["code"] == "forbidden"
        billing_post.assert_not_called()

    @parameterized.expand(
        [
            ("activation_grants_more_projects", 201, 200),
            ("activation_fails", 500, 403),
        ]
    )
    def test_create_with_new_project_id_activates_billing_from_payment_token_before_the_plan_limit(
        self, _name: str, activation_status: int, expected_status: int
    ) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        token = self._get_bearer_token()
        team_count = Team.objects.filter(organization=self.organization).count()
        activation_response = requests.Response()
        activation_response.status_code = activation_status
        license = License(key="12345::67890")

        with (
            patch("ee.partners.stripe.api.provisioning.billing.get_cached_instance_license", return_value=license),
            patch("ee.partners.stripe.api.provisioning.core.get_cached_instance_license", return_value=license),
            patch("ee.partners.stripe.api.provisioning.billing._team_has_active_billing", return_value=False),
            patch("ee.billing.billing_manager.http_session.post", return_value=activation_response) as billing_post,
            patch("ee.billing.billing_manager.http_session.get") as billing_get,
        ):
            billing_get.return_value.status_code = 200
            billing_get.return_value.json.return_value = {"available_product_features": [SIX_PROJECTS_FEATURE]}
            res = self._post_signed_with_bearer(
                RESOURCES_URL,
                data={
                    "project_id": "proj_paid",
                    "payment_credentials": {"type": "stripe_payment_token", "stripe_payment_token": "spt_1"},
                },
                token=token,
            )

        assert res.status_code == expected_status, res.json()
        assert billing_post.call_args_list[0].kwargs["json"] == {"shared_payment_token": "spt_1"}
        expected_team_count = team_count + 1 if expected_status == 200 else team_count
        assert Team.objects.filter(organization=self.organization).count() == expected_team_count

    @parameterized.expand([("203.0.113.7", 200), ("198.51.100.7", 403)])
    def test_bearer_checks_organization_ip_policy(self, ip: str, expected_status: int) -> None:
        token = self._get_bearer_token()
        OrganizationIPRestrictions.objects.create(organization=self.organization, ip_restrictions=["203.0.113.0/24"])

        response = self._post_signed_with_bearer(RESOURCES_URL, {}, token=token, REMOTE_ADDR=ip)

        assert response.status_code == expected_status, response.content
        if expected_status == 403:
            assert response.json()["status"] == "error"
            assert response.json()["error"]["code"] == "forbidden"
            assert "IP address" in response.json()["error"]["message"]

    def test_deactivated_user_bearer_token_rejected(self):
        token = self._get_bearer_token()

        self.user.is_active = False
        self.user.save()

        res = self._post_signed_with_bearer(RESOURCES_URL, data={}, token=token)
        assert res.status_code == 401

    @parameterized.expand(
        [
            ("read_access_control_revoked", "read", "access_control"),
            ("read_org_membership_removed", "read", "membership"),
            ("create_access_control_revoked", "create", "access_control"),
            ("create_org_membership_removed", "create", "membership"),
        ]
    )
    def test_resource_endpoints_rejected_after_team_access_lost(self, _name: str, endpoint: str, revocation: str):
        token = self._get_bearer_token()

        if revocation == "access_control":
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            ]
            self.organization.save()
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            AccessControl.objects.create(
                team=self.team,
                access_level="none",
                resource="project",
                resource_id=str(self.team.id),
            )
        else:
            self.organization_membership.delete()

        if endpoint == "read":
            res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token)
        else:
            res = self._post_signed_with_bearer(RESOURCES_URL, data={}, token=token)

        assert res.status_code == 403

    def test_unknown_service_rejected(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(RESOURCES_URL, data={"service_id": "nonsense"}, token=token)
        assert res.status_code == 400
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "unknown_service", "message": "Unknown service_id: nonsense"},
        }

    @parameterized.expand(
        [
            ("too_long", "x" * 26, "label_prefix must be 25 characters or fewer"),
            ("bidi_override", "evil‮prefix", "label_prefix must not contain control or format characters"),
            ("non_string", 123, "label_prefix must be a string"),
        ]
    )
    def test_invalid_label_prefix_rejected(self, _name, prefix, message):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(RESOURCES_URL, data={"label_prefix": prefix}, token=token)
        assert res.status_code == 400
        assert res.json()["error"] == {"code": "invalid_label_prefix", "message": message}

    def test_pay_as_you_go_requires_payment_credentials(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(RESOURCES_URL, data={"service_id": "pay_as_you_go"}, token=token)
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "requires_payment_credentials"

    def test_pay_as_you_go_with_spt_activates_billing(self):
        token = self._get_bearer_token()
        with (
            patch("ee.partners.stripe.api.provisioning.billing._team_has_active_billing", return_value=False),
            patch(
                "ee.partners.stripe.api.provisioning.billing._activate_billing_with_spt", return_value=True
            ) as activate,
        ):
            res = self._post_signed_with_bearer(
                RESOURCES_URL,
                data={
                    "service_id": "pay_as_you_go",
                    "payment_credentials": {"type": "stripe_payment_token", "stripe_payment_token": "spt_1"},
                },
                token=token,
            )
        assert res.status_code == 200
        assert res.json()["service_id"] == "pay_as_you_go"
        activate.assert_called_once()
        assert activate.call_args[0][2] == "spt_1"

    def test_failed_spt_activation_is_reported(self):
        token = self._get_bearer_token()
        with (
            patch("ee.partners.stripe.api.provisioning.billing._team_has_active_billing", return_value=False),
            patch("ee.partners.stripe.api.provisioning.billing._activate_billing_with_spt", return_value=False),
        ):
            res = self._post_signed_with_bearer(
                RESOURCES_URL,
                data={
                    "service_id": "analytics",
                    "payment_credentials": {"type": "stripe_payment_token", "stripe_payment_token": "spt_1"},
                },
                token=token,
            )
        assert res.status_code == 400
        assert res.json() == {
            "status": "error",
            "id": str(self.team.id),
            "error": {"code": "requires_payment_credentials", "message": "Billing activation failed"},
        }

    def test_rate_limited_spt_activation_logs_a_warning_instead_of_an_error(self) -> None:
        token = self._get_bearer_token()
        billing_response = requests.Response()
        billing_response.status_code = 429
        billing_response.headers["Retry-After"] = "30"
        billing_response.raw = MagicMock()

        with (
            patch(
                "ee.partners.stripe.api.provisioning.billing.get_cached_instance_license",
                return_value=License(key="12345::67890"),
            ),
            patch("ee.partners.stripe.api.provisioning.billing._team_has_active_billing", return_value=False),
            patch("ee.billing.billing_manager.http_session.post", return_value=billing_response),
            patch("ee.partners.stripe.api.provisioning.billing.capture_exception") as capture,
            patch("ee.partners.stripe.api.provisioning.billing.logger") as logger,
        ):
            res = self._post_signed_with_bearer(
                RESOURCES_URL,
                data={
                    "service_id": "analytics",
                    "payment_credentials": {"type": "stripe_payment_token", "stripe_payment_token": "spt_1"},
                },
                token=token,
            )

        assert res.status_code == 400
        assert res.json()["error"]["message"] == "Billing activation failed"
        capture.assert_not_called()
        logger.warning.assert_called_once_with(
            "stripe_provisioning.spt_billing_rate_limited",
            team_id=self.team.id,
            org_id=str(self.team.organization_id),
        )

    @parameterized.expand(
        [
            ("partner_billed", None, 400, []),
            ("partner_billed_org_with_own_stripe_customer", "cus_example", 200, [{"shared_payment_token": "spt_1"}]),
        ]
    )
    def test_spt_activates_billing_unless_billing_is_locked_to_the_partner(
        self, _name: str, customer_id: str | None, expected_status: int, expected_billing_payloads: list[dict[str, str]]
    ) -> None:
        self.stripe_app.update_provisioning(pays_for_customers=True)
        OrganizationProvisioning.objects.create(
            organization=self.organization,
            partner=OrganizationProvisioning.Partner.STRIPE_PROJECTS,
            application=self.stripe_app,
        )
        self.organization.customer_id = customer_id
        self.organization.save(update_fields=["customer_id"])
        token = self._get_bearer_token()
        billing_response = requests.Response()
        billing_response.status_code = 201

        with (
            patch(
                "ee.partners.stripe.api.provisioning.billing.get_cached_instance_license",
                return_value=License(key="12345::67890"),
            ),
            patch("ee.partners.stripe.api.provisioning.billing._team_has_active_billing", return_value=False),
            patch("ee.billing.billing_manager.http_session.post", return_value=billing_response) as billing_post,
        ):
            res = self._post_signed_with_bearer(
                RESOURCES_URL,
                data={
                    "service_id": "pay_as_you_go",
                    "payment_credentials": {"type": "stripe_payment_token", "stripe_payment_token": "spt_1"},
                },
                token=token,
            )

        assert res.status_code == expected_status, res.json()
        assert [call.kwargs["json"] for call in billing_post.call_args_list] == expected_billing_payloads

    @covers_authentication(StripeBearerAuthentication)
    def test_detail_returns_resource(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token)
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "complete"
        assert body["id"] == str(self.team.id)
        assert body["complete"]["access_configuration"]["api_key"] == self.team.api_token

    @parameterized.expand(
        [
            ("non_numeric", "abc", 400, "invalid_resource_id"),
            ("out_of_scope", "999999", 403, "forbidden"),
        ]
    )
    def test_detail_rejects_bad_resource_ids(self, _name, resource_id, status, code):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{resource_id}", token=token)
        assert res.status_code == status
        body = res.json()
        assert body["status"] == "error"
        assert body["id"] == resource_id
        assert body["error"]["code"] == code

    @parameterized.expand(
        [
            ("missing", None, "Missing bearer token"),
            ("unknown", "pha_bogus", "Invalid access token"),
        ]
    )
    def test_bearer_required(self, _name, token, message):
        if token is None:
            res = self.client.get(f"{RESOURCES_URL}/{self.team.id}", HTTP_API_VERSION="0.1d")
        else:
            res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token)
        assert res.status_code == 401
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "unauthorized", "message": message},
        }

    def test_signature_required_even_with_valid_bearer(self):
        token = self._get_bearer_token()
        res = self.client.get(
            f"{RESOURCES_URL}/{self.team.id}",
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert res.status_code == 401
        assert res.json() == {"error": {"code": "invalid_signature", "message": "Signature verification failed"}}

    def test_bearer_from_another_app_rejected(self):
        # Authorization is by identity alone: a token for any app other than the
        # Stripe Projects app is rejected regardless of its config.
        other_app = self._create_other_partner_app()
        token_value = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            application=other_app,
            token=token_value,
            user=self.user,
            expires=timezone.now() + timedelta(days=1),
            scope="query:read",
            scoped_teams=[self.team.id],
        )

        res = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token_value)
        assert res.status_code == 401
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "unauthorized", "message": "Authentication failed"},
        }
