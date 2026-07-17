from io import StringIO

from django.core.management import call_command
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

    def test_issuance_rejected_when_no_accessible_teams(self):
        # When the base team is gone or the user lost access, _compute_partner_scoped_teams
        # returns []. An empty scoped_teams is unrestricted under the standard permission
        # check, so issuance must fail closed rather than mint a project-unrestricted token.
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

        res = self._request_bearer_token()
        assert res.status_code == 400, res.content
        assert res.json()["error"] == "invalid_grant"
        assert not OAuthAccessToken.objects.filter(user=self.user).exists()

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

    def test_refresh_rejected_when_access_lost_and_token_preserved(self):
        # A refresh whose base team access was revoked recomputes to an empty scope.
        # It must fail closed (not rotate into an unrestricted token) and, because the
        # check runs before any token mutation, must leave the caller's refresh token intact.
        from posthog.constants import AvailableFeature
        from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken
        from posthog.models.organization import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

        token = self._get_bearer_token()
        refresh_token = OAuthRefreshToken.objects.get(access_token__token=token)

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

        res = self._post_signed(
            "/api/agentic/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": refresh_token.token},
            content_type="application/x-www-form-urlencoded",
        )
        assert res.status_code == 400, res.content
        assert res.json()["error"] == "invalid_grant"

        refresh_token.refresh_from_db()
        assert refresh_token.revoked is None
        assert OAuthAccessToken.objects.filter(token=token).exists()

    def test_backfill_rehydrates_stale_access_and_refresh_scope(self):
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
        from posthog.models.team.team import Team
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        refresh_token = OAuthRefreshToken.objects.get(access_token=access_token)
        assert access_token.scoped_teams == [self.team.id]

        stripe_app = OAuthApplication.objects.get(client_id="test_stripe_oauth_client_id")
        stripe_app.provisioning_partner_type = "stripe"
        stripe_app.save()
        newly_provisioned = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Newly provisioned",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=newly_provisioned,
            defaults={"stripe_project_id": "proj_new", "application": stripe_app},
        )

        call_command("backfill_agentic_provisioning_scope", stdout=StringIO())

        access_token.refresh_from_db()
        refresh_token.refresh_from_db()
        assert self.team.id in access_token.scoped_teams
        assert newly_provisioned.id in access_token.scoped_teams
        assert self.team.id in refresh_token.scoped_teams
        assert newly_provisioned.id in refresh_token.scoped_teams

    def test_backfill_leaves_scope_unchanged_when_recomputed_scope_is_empty(self):
        # When the user has lost access, _compute_partner_scoped_teams returns [].
        # An empty scoped_teams is unrestricted under the standard permission check, so the
        # backfill must NOT overwrite a restricted token with [] — it leaves the existing
        # restriction intact and reports the token for re-authorization.
        from posthog.constants import AvailableFeature
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
        from posthog.models.organization import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        refresh_token = OAuthRefreshToken.objects.get(access_token=access_token)
        assert access_token.scoped_teams == [self.team.id]

        stripe_app = OAuthApplication.objects.get(client_id="test_stripe_oauth_client_id")
        stripe_app.provisioning_partner_type = "stripe"
        stripe_app.save()

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

        out = StringIO()
        call_command("backfill_agentic_provisioning_scope", stdout=out)

        access_token.refresh_from_db()
        refresh_token.refresh_from_db()
        assert access_token.scoped_teams == [self.team.id]
        assert refresh_token.scoped_teams == [self.team.id]
        assert "needs re-authorization" in out.getvalue()

    def test_application_none_yields_empty_scope(self):
        # application is never None in practice (oauthrefreshtoken.application_id is
        # NOT NULL and issuance always resolves an app), so this pins the helper's
        # defensive branch: an unattributed token fails closed with no scope rather
        # than silently retaining the base team.
        from ee.api.agentic_provisioning.views import _compute_partner_scoped_teams

        assert _compute_partner_scoped_teams(None, self.user, self.team.id) == []
