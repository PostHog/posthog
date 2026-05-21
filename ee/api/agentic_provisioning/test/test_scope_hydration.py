from django.test import override_settings

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestPartnerTokenScopeHydration(ProvisioningTestBase):
    def test_issuance_hydrates_with_previously_provisioned_teams(self):
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        stripe_app = OAuthApplication.objects.get(client_id="test_stripe_oauth_client_id")
        previously_provisioned = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Previously provisioned",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=previously_provisioned,
            defaults={"stripe_project_id": "proj_existing", "application": stripe_app},
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert self.team.id in access_token.scoped_teams
        assert previously_provisioned.id in access_token.scoped_teams

    def test_other_partner_teams_excluded(self):
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        other_partner = OAuthApplication.objects.create(
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
            name="Other partner team",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=other_partner_team,
            defaults={"stripe_project_id": "proj_other", "application": other_partner},
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert other_partner_team.id not in access_token.scoped_teams

    def test_other_org_team_excluded_even_when_user_is_member(self):
        # Same partner provisions teams in two orgs the user belongs to.
        # The token is granted under org A's authorization; org B's team must
        # not leak in just because the user can access it via org B membership.
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        stripe_app = OAuthApplication.objects.get(client_id="test_stripe_oauth_client_id")
        other_org = Organization.objects.create(name="Other org")
        OrganizationMembership.objects.create(
            organization=other_org,
            user=self.user,
            level=OrganizationMembership.Level.ADMIN,
        )
        other_org_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=other_org,
            name="Same partner, other org",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=other_org_team,
            defaults={"stripe_project_id": "proj_other_org", "application": stripe_app},
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert self.team.id in access_token.scoped_teams
        assert other_org_team.id not in access_token.scoped_teams

    def test_cross_org_teams_excluded(self):
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication
        from posthog.models.organization import Organization
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        stripe_app = OAuthApplication.objects.get(client_id="test_stripe_oauth_client_id")
        other_org = Organization.objects.create(name="Other org")
        foreign_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=other_org,
            name="Foreign team",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=foreign_team,
            defaults={"stripe_project_id": "proj_foreign", "application": stripe_app},
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert foreign_team.id not in access_token.scoped_teams

    def test_team_with_revoked_access_excluded(self):
        from posthog.constants import AvailableFeature
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication
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

        stripe_app = OAuthApplication.objects.get(client_id="test_stripe_oauth_client_id")
        restricted_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Restricted team",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=restricted_team,
            defaults={"stripe_project_id": "proj_restricted", "application": stripe_app},
        )
        AccessControl.objects.create(
            team=restricted_team,
            access_level="none",
            resource="project",
            resource_id=str(restricted_team.id),
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert restricted_team.id not in access_token.scoped_teams

    def test_base_team_excluded_when_user_loses_access(self):
        # base_team_id must not be unconditionally included. If the user has
        # since lost access to it, the new token should not carry it.
        from posthog.constants import AvailableFeature
        from posthog.models.oauth import OAuthAccessToken
        from posthog.models.organization import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

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

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert self.team.id not in access_token.scoped_teams

    def test_refresh_rehydrates_with_new_teams(self):
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        refresh_token = OAuthRefreshToken.objects.get(access_token=access_token)
        assert access_token.scoped_teams == [self.team.id]

        stripe_app = OAuthApplication.objects.get(client_id="test_stripe_oauth_client_id")
        newly_provisioned = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Newly provisioned",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=newly_provisioned,
            defaults={"stripe_project_id": "proj_new", "application": stripe_app},
        )

        res = self._post_signed(
            "/api/agentic/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token.token},
            content_type="application/x-www-form-urlencoded",
        )
        assert res.status_code == 200, res.content
        new_access_token = OAuthAccessToken.objects.get(token=res.json()["access_token"])
        assert self.team.id in new_access_token.scoped_teams
        assert newly_provisioned.id in new_access_token.scoped_teams
