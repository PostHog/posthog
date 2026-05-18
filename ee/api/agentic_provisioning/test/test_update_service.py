from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestProvisioningUpdateService(ProvisioningTestBase):
    @patch("ee.api.agentic_provisioning.views.requests.post")
    @patch("ee.billing.billing_manager.build_billing_token", return_value="test_billing_token")
    @patch("posthog.cloud_utils.get_cached_instance_license")
    def test_update_service_with_spt_calls_billing(self, mock_license, mock_build_token, mock_post):
        mock_license.return_value = MagicMock()
        mock_post.return_value = MagicMock(status_code=200)

        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={
                "service_id": "pay_as_you_go",
                "payment_credentials": {
                    "type": "stripe_payment_token",
                    "stripe_payment_token": "spt_test_123",
                },
            },
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert res.json()["service_id"] == "pay_as_you_go"

        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert "/api/activate/authorize" in call_args[0]
        assert call_kwargs["json"] == {"shared_payment_token": "spt_test_123"}

    @parameterized.expand(
        [
            ("billing_inactive", False, 400, "billing_activation_failed"),
            ("billing_already_active", True, 200, "complete"),
        ]
    )
    @patch("ee.api.agentic_provisioning.views.requests.get")
    @patch("ee.api.agentic_provisioning.views.requests.post")
    @patch("ee.billing.billing_manager.build_billing_token", return_value="test_billing_token")
    @patch("posthog.cloud_utils.get_cached_instance_license")
    def test_update_service_spt_failure(
        self,
        _name,
        has_active_subscription,
        expected_status,
        expected_code,
        mock_license,
        mock_build_token,
        mock_post,
        mock_get,
    ):
        mock_license.return_value = MagicMock()
        mock_post.return_value = MagicMock(status_code=500)
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: {"customer": {"has_active_subscription": has_active_subscription}}
        )

        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={
                "service_id": "pay_as_you_go",
                "payment_credentials": {
                    "type": "stripe_payment_token",
                    "stripe_payment_token": "spt_test_123",
                },
            },
            token=token,
        )
        assert res.status_code == expected_status
        body = res.json()
        if expected_status == 400:
            assert body["error"]["code"] == expected_code
        else:
            assert body["status"] == expected_code
            assert body["service_id"] == "pay_as_you_go"

    def test_update_service_without_spt_to_free_succeeds(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={"service_id": "free"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["service_id"] == "free"
        assert "api_key" in data["complete"]["access_configuration"]
        assert "host" in data["complete"]["access_configuration"]

    def test_update_service_to_pay_as_you_go_without_spt_returns_error(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={"service_id": "pay_as_you_go"},
            token=token,
        )
        assert res.status_code == 400
        body = res.json()
        assert body["status"] == "error"
        assert body["error"]["code"] == "requires_payment_credentials"

    def test_update_service_rejects_unknown_service_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={"service_id": "unknown_service"},
            token=token,
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "unknown_service"

    def test_update_service_requires_service_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={},
            token=token,
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "missing_service_id"

    def test_update_service_wrong_team_returns_403(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources/99999/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 403

    def test_update_service_missing_bearer_returns_401(self):
        res = self._post_signed(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={"service_id": "analytics"},
        )
        assert res.status_code == 401

    def test_update_service_invalid_resource_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources/not-a-number/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 400

    def test_update_service_auto_adds_provisioned_team_in_same_org_to_scope(self):
        from posthog.models.oauth import OAuthAccessToken
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)

        # Team that was provisioned earlier by this partner but isn't in this
        # access token's scope (e.g. customer re-OAuth'd, dropping it).
        existing_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Pre-existing project",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=existing_team,
            defaults={"stripe_project_id": "proj_existing", "application": access_token.application},
        )
        assert existing_team.id not in (access_token.scoped_teams or [])

        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{existing_team.id}/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 200, res.json()
        access_token.refresh_from_db()
        assert existing_team.id in access_token.scoped_teams

    def test_update_service_rejects_team_in_other_org(self):
        from posthog.models.oauth import OAuthAccessToken
        from posthog.models.organization import Organization
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)

        other_org = Organization.objects.create(name="Other org")
        foreign_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=other_org,
            name="Foreign project",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=foreign_team,
            defaults={"stripe_project_id": "proj_foreign", "application": access_token.application},
        )

        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{foreign_team.id}/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 403

    def test_update_service_rejects_team_provisioned_by_other_partner(self):
        # Cross-partner scope escalation guard: team T was provisioned by
        # partner A in org O. Partner B's bearer token is also scoped to org
        # O (different team). B must not be able to auto-add T to its scope.
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        other_partner_app = OAuthApplication.objects.create(
            name="Other Partner",
            client_id="other_partner_client_id",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
            provisioning_partner_type="other_partner",
        )
        other_partner_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Other partner's project",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=other_partner_team,
            defaults={"stripe_project_id": "proj_other", "application": other_partner_app},
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert access_token.application_id != other_partner_app.id

        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{other_partner_team.id}/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 403
        access_token.refresh_from_db()
        assert other_partner_team.id not in (access_token.scoped_teams or [])

    def test_update_service_rejects_same_org_team_not_provisioned_by_partner(self):
        from posthog.models.team.team import Team

        # Same-org team. A `TeamProvisioningConfig` row is auto-created on every
        # team (post_save signal), but its `stripe_project_id` is None because
        # the team was created outside the partner flow. The partner has no
        # claim on it.
        unprovisioned_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Hand-rolled project",
        )

        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{unprovisioned_team.id}/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 403

    def test_update_service_rejects_when_user_lacks_team_access(self):
        from posthog.constants import AvailableFeature
        from posthog.models.oauth import OAuthAccessToken
        from posthog.models.organization import OrganizationMembership
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)

        restricted_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Restricted project",
        )
        # Set `application` so the team passes the partner-binding check;
        # otherwise the auto-add would reject before the ACL check runs and the
        # test would pass for the wrong reason.
        TeamProvisioningConfig.objects.update_or_create(
            team=restricted_team,
            defaults={"stripe_project_id": "proj_restricted", "application": access_token.application},
        )
        AccessControl.objects.create(
            team=restricted_team,
            access_level="none",
            resource="project",
            resource_id=str(restricted_team.id),
        )

        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{restricted_team.id}/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 403

    def test_update_service_rejects_in_scope_team_when_user_access_revoked(self):
        # Team is already in the bearer token's scoped_teams (from an earlier
        # call when the user had access), but advanced permissions have since
        # revoked it. ACL must be re-checked on the short-circuit, otherwise
        # stale scope grants ongoing access after access controls tighten.
        from posthog.constants import AvailableFeature
        from posthog.models.oauth import OAuthAccessToken
        from posthog.models.organization import OrganizationMembership
        from posthog.models.team.team import Team

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Use a fresh team rather than self.team so AC isn't shadowed by any
        # implicit grant the test base seeds for the default project.
        scoped_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Stale-scope project",
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        access_token.scoped_teams = [*access_token.scoped_teams, scoped_team.id]
        access_token.save(update_fields=["scoped_teams"])

        AccessControl.objects.create(
            team=scoped_team,
            access_level="none",
            resource="project",
            resource_id=str(scoped_team.id),
        )

        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{scoped_team.id}/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 403
