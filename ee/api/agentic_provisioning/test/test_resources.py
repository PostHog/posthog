from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.accessible_teams import AccessibleTeams
from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_ip_restrictions import OrganizationIPRestrictions
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User
from posthog.personal_api_key_minting import mint_personal_api_key
from posthog.project_creation_limits import (
    ORGANIZATION_PROJECT_LIMIT_MESSAGE,
    PLAN_PROJECT_LIMIT_MESSAGE,
    PROJECT_CREATION_REQUIRES_ADMIN_MESSAGE,
)
from posthog.test.authentication_checks import covers_authentication

from products.access_control.backend.models.access_control import AccessControl

from ee.api.agentic_provisioning.authentication import ProvisioningBearerAuthentication
from ee.api.agentic_provisioning.credentials import maybe_create_provisioned_pat
from ee.api.agentic_provisioning.ratelimits import RATE_LIMITED_MESSAGE
from ee.api.agentic_provisioning.test.base import ProvisioningTestBase, provisioning_config

RESOURCES_URL = "/api/agentic/provisioning/resources"
UNLIMITED_PROJECTS_FEATURE = {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": None}
ONE_PROJECT_FEATURE = {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": 1}
PROJECT_WRITE_SCOPES = ["query:read", "project:write"]
MEMBERS_CAN_CREATE_PROJECTS_FEATURE = {
    "key": AvailableFeature.ORGANIZATION_INVITE_SETTINGS,
    "name": AvailableFeature.ORGANIZATION_INVITE_SETTINGS,
}


class TestProvisioningResources(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self._set_organization_features([UNLIMITED_PROJECTS_FEATURE])
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _bearer_token_with_scopes(self, scopes: list[str]) -> str:
        # The partner's own scopes cap what a token can carry, so widen them first.
        self.partner.scopes = sorted({*self.partner.scopes, *scopes})
        self.partner.save()
        return self._request_bearer_token(scopes=scopes).json()["access_token"]

    def _set_organization_features(self, features: list[dict]) -> None:
        self.organization.available_product_features = features
        self.organization.save()

    @parameterized.expand(
        [
            ("without_projects_feature", [], None, PLAN_PROJECT_LIMIT_MESSAGE),
            ("at_plan_limit", [ONE_PROJECT_FEATURE], None, PLAN_PROJECT_LIMIT_MESSAGE),
            ("at_organization_maximum", [UNLIMITED_PROJECTS_FEATURE], 1, ORGANIZATION_PROJECT_LIMIT_MESSAGE),
            (
                "at_organization_maximum_below_the_plan_limit",
                [{**ONE_PROJECT_FEATURE, "limit": 5000}],
                1,
                ORGANIZATION_PROJECT_LIMIT_MESSAGE,
            ),
        ]
    )
    def test_create_resource_with_new_project_id_refused_at_project_limit(
        self, _name: str, features: list[dict], organization_maximum: int | None, message: str
    ) -> None:
        self._set_organization_features(features)
        token = self._get_bearer_token()
        team_count = Team.objects.filter(organization=self.organization).count()

        with patch(
            "posthog.project_creation_limits.MAX_ALLOWED_PROJECTS_PER_ORG",
            organization_maximum or 2000,
        ):
            res = self._post_with_bearer(RESOURCES_URL, data={"project_id": "proj_over_limit"}, token=token)

        assert res.status_code == 403
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "project_limit_reached", "message": message},
        }
        assert Team.objects.filter(organization=self.organization).count() == team_count
        assert not TeamProvisioningConfig.objects.filter(stripe_project_id="proj_over_limit").exists()

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, False, 403),
            ("member_when_organization_allows_it", OrganizationMembership.Level.MEMBER, True, 200),
            ("admin", OrganizationMembership.Level.ADMIN, False, 200),
        ]
    )
    def test_create_resource_with_new_project_id_follows_project_creation_policy(
        self, _name: str, level: OrganizationMembership.Level, members_can_create_projects: bool, expected_status: int
    ) -> None:
        self._set_organization_features([UNLIMITED_PROJECTS_FEATURE, MEMBERS_CAN_CREATE_PROJECTS_FEATURE])
        self.organization.members_can_create_projects = members_can_create_projects
        self.organization.save()
        self.organization_membership.level = level
        self.organization_membership.save()
        token = self._get_bearer_token()
        team_count = Team.objects.filter(organization=self.organization).count()

        res = self._post_with_bearer(RESOURCES_URL, data={"project_id": "proj_policy"}, token=token)

        assert res.status_code == expected_status, res.content
        if expected_status == 403:
            assert res.json()["error"] == {"code": "forbidden", "message": PROJECT_CREATION_REQUIRES_ADMIN_MESSAGE}
            assert Team.objects.filter(organization=self.organization).count() == team_count
        else:
            assert Team.objects.filter(organization=self.organization).count() == team_count + 1

    def test_first_new_project_id_claims_the_partner_project_and_a_second_is_refused_on_free_plan(self) -> None:
        self._set_organization_features([])
        TeamProvisioningConfig.objects.create(team=self.team, application=self.partner)
        token = self._bearer_token_with_scopes(PROJECT_WRITE_SCOPES)

        first = self._post_with_bearer(
            RESOURCES_URL,
            data={"project_id": "proj_first", "configuration": {"project_name": "Partner app"}},
            token=token,
        )
        repeated = self._post_with_bearer(RESOURCES_URL, data={"project_id": "proj_first"}, token=token)
        second = self._post_with_bearer(RESOURCES_URL, data={"project_id": "proj_second"}, token=token)

        assert first.status_code == 200, first.content
        assert first.json()["id"] == str(self.team.id)
        assert repeated.json()["id"] == str(self.team.id)
        assert TeamProvisioningConfig.objects.get(team=self.team).stripe_project_id == "proj_first"
        assert Team.objects.get(id=self.team.id).name == "Partner app"
        assert second.status_code == 403
        assert second.json()["error"]["code"] == "project_limit_reached"
        assert list(Team.objects.filter(organization=self.organization).values_list("id", flat=True)) == [self.team.id]

    @parameterized.expand(
        [
            ("admin", OrganizationMembership.Level.ADMIN, PROJECT_WRITE_SCOPES, "Partner app"),
            ("admin_with_a_read_only_token", OrganizationMembership.Level.ADMIN, ["query:read"], "Bootstrap project"),
            ("member", OrganizationMembership.Level.MEMBER, PROJECT_WRITE_SCOPES, "Bootstrap project"),
        ]
    )
    def test_claim_applies_the_requested_name_only_for_project_admins_with_project_write(
        self, _name: str, level: OrganizationMembership.Level, scopes: list[str], expected_name: str
    ) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()
        self.team.name = "Bootstrap project"
        self.team.save()
        Project.objects.filter(id=self.team.id).update(name="Bootstrap project")
        TeamProvisioningConfig.objects.create(team=self.team, application=self.partner)
        token = self._bearer_token_with_scopes(scopes)

        res = self._post_with_bearer(
            RESOURCES_URL,
            data={"project_id": "proj_named", "configuration": {"project_name": "Partner app"}},
            token=token,
        )

        assert res.status_code == 200, res.content
        assert res.json()["id"] == str(self.team.id)
        assert Team.objects.get(id=self.team.id).name == expected_name
        assert Project.objects.get(id=self.team.id).name == expected_name

    def test_new_project_id_resolves_to_a_concurrent_claim_of_the_same_project_id(self) -> None:
        self._set_organization_features([])
        config = TeamProvisioningConfig.objects.create(team=self.team, application=self.partner)
        token = self._get_bearer_token()

        def lose_claim_to_concurrent_request(project_id: str, *args, **kwargs) -> None:
            config.stripe_project_id = project_id
            config.save()

        with patch(
            "ee.api.agentic_provisioning.teams._claim_provisioned_team", side_effect=lose_claim_to_concurrent_request
        ):
            res = self._post_with_bearer(RESOURCES_URL, data={"project_id": "proj_raced"}, token=token)

        assert res.status_code == 200, res.content
        assert res.json()["id"] == str(self.team.id)

    @parameterized.expand(
        [
            ("not_a_string", 123),
            ("null", None),
            ("empty", ""),
            ("too_long", "x" * 201),
            ("null_character", "Partner\x00app"),
        ]
    )
    def test_create_resource_rejects_invalid_project_name_without_claiming(
        self, _name: str, project_name: object
    ) -> None:
        TeamProvisioningConfig.objects.create(team=self.team, application=self.partner)
        token = self._get_bearer_token()

        res = self._post_with_bearer(
            RESOURCES_URL,
            data={"project_id": "proj_named", "configuration": {"project_name": project_name}},
            token=token,
        )

        assert res.status_code == 400
        assert res.json()["error"] == {
            "code": "invalid_request",
            "message": "configuration: project_name must be a string of 1 to 200 characters",
        }
        assert TeamProvisioningConfig.objects.get(team=self.team).stripe_project_id is None

    @parameterized.expand(
        [
            ("claimed_by_another_project_id", "proj_existing", None),
            ("provisioned_by_another_partner", None, "other_partner"),
            ("not_provisioned_by_a_partner", None, "none"),
            ("this_partners_project_other_than_the_base_team", None, "other_team"),
        ]
    )
    def test_new_project_id_does_not_claim_a_project_unavailable_to_this_partner(
        self, _name: str, existing_project_id: str | None, owner: str | None
    ) -> None:
        other_team = None
        if owner == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="Teammate's partner project")
            TeamProvisioningConfig.objects.create(team=other_team, application=self.partner)
        elif owner != "none":
            application = (
                OAuthApplication.objects.create(
                    name="Other example partner",
                    client_id="other_example_partner",
                    client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                    authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    redirect_uris="https://other.example.com/callback",
                    algorithm="RS256",
                )
                if owner == "other_partner"
                else self.partner
            )
            TeamProvisioningConfig.objects.create(
                team=self.team, application=application, stripe_project_id=existing_project_id
            )
        token = self._get_bearer_token()

        res = self._post_with_bearer(RESOURCES_URL, data={"project_id": "proj_new"}, token=token)

        assert res.status_code == 200, res.content
        assert res.json()["id"] != str(self.team.id)
        assert TeamProvisioningConfig.objects.filter(team=self.team, stripe_project_id="proj_new").count() == 0
        if other_team is not None:
            assert other_team.id in OAuthAccessToken.objects.get(token=token).scoped_teams
            assert res.json()["id"] != str(other_team.id)
            assert TeamProvisioningConfig.objects.get(team=other_team).stripe_project_id is None

    @parameterized.expand(
        [
            (operation, ip, restrict_target, expected)
            for operation in ("create", "read", "rotate", "remove", "new_project", "existing_project", "deep_link")
            for ip, restrict_target, expected in (
                ("203.0.113.7", True, 200),
                ("198.51.100.7", True, 403),
                ("198.51.100.7", False, 200),
            )
        ]
    )
    def test_resource_ip_policy_follows_target(
        self, operation: str, ip: str, restrict_target: bool, expected: int
    ) -> None:
        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        if operation == "existing_project":
            existing = Team.objects.create(organization=self.organization, name="Existing example project")
            TeamProvisioningConfig.objects.update_or_create(
                team=existing, defaults={"stripe_project_id": "example-policy-project", "application": self.partner}
            )
        other = Organization.objects.create(name="Other example organization")
        other_team = Team.objects.create(organization=other)
        self.user.join(organization=other)
        self.user.current_team = other_team
        self.user.save()
        OrganizationIPRestrictions.objects.create(
            organization=self.organization if restrict_target else other, ip_restrictions=["203.0.113.0/24"]
        )
        self.client.defaults["REMOTE_ADDR"] = ip
        original_key = self.team.api_token
        original_scopes = access_token.scoped_teams
        original_teams = Team.objects.filter(organization=self.organization).count()
        original_mappings = TeamProvisioningConfig.objects.count()
        original_credentials = PersonalAPIKey.objects.count()
        url = "/api/agentic/provisioning/resources"
        data: dict[str, str] = {}
        if operation in ("new_project", "existing_project"):
            data = {"project_id": "example-policy-project"}
        elif operation == "deep_link":
            url = "/api/agentic/provisioning/deep_links"
            data = {"purpose": "dashboard"}
        elif operation in ("read", "rotate", "remove"):
            url += f"/{self.team.id}"
            url += {"read": "", "rotate": "/rotate_credentials", "remove": "/remove"}[operation]
        response = (
            self._get_with_bearer(url, token=token)
            if operation == "read"
            else self._post_with_bearer(url, data, token=token)
        )
        assert response.status_code == expected, response.content
        if expected == 403:
            assert response.json()["error"]["code"] == "forbidden"
            self.team.refresh_from_db()
            access_token.refresh_from_db()
            assert self.team.api_token == original_key
            assert access_token.scoped_teams == original_scopes
            assert Team.objects.filter(organization=self.organization).count() == original_teams
            assert TeamProvisioningConfig.objects.count() == original_mappings
            assert PersonalAPIKey.objects.count() == original_credentials

    @covers_authentication(ProvisioningBearerAuthentication)
    def test_create_resource_returns_complete(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)
        assert "api_key" in data["complete"]["access_configuration"]
        assert "host" in data["complete"]["access_configuration"]

    def test_create_resource_rate_limited_uses_status_envelope(self):
        self.partner.update_provisioning_rate_limits(resource_creates=1)
        token = self._get_bearer_token()

        assert self._post_with_bearer("/api/agentic/provisioning/resources", token=token).status_code == 200

        res = self._post_with_bearer("/api/agentic/provisioning/resources", token=token)
        assert res.status_code == 429
        assert res["Retry-After"]

        # Resource endpoints speak the "status" envelope, not the typed one.
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {"code": "rate_limited", "message": RATE_LIMITED_MESSAGE},
        }

    @patch("ee.api.agentic_provisioning.views.resources.capture_provisioning_event")
    def test_create_resource_capture_attributes_client(self, mock_capture_event):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        assert res.status_code == 200

        success_calls = [
            call for call in mock_capture_event.call_args_list if call.args[:2] == ("resource_created", "success")
        ]
        assert len(success_calls) == 1
        partner = success_calls[0].kwargs["partner"]
        assert partner is not None
        assert partner.name == "Test Provisioning Partner"

    def test_get_resource_returns_complete(self):
        token = self._get_bearer_token()
        res = self._get_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)

    def test_get_resource_wrong_team_returns_403(self):
        token = self._get_bearer_token()
        res = self._get_with_bearer(
            "/api/agentic/provisioning/resources/99999",
            token=token,
        )
        assert res.status_code == 403

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
            self._restrict_team_access(self.team)
        else:
            self.organization_membership.delete()

        if endpoint == "read":
            res = self._get_with_bearer(f"/api/agentic/provisioning/resources/{self.team.id}", token=token)
        else:
            res = self._post_with_bearer("/api/agentic/provisioning/resources", {}, token=token)

        assert res.status_code == 403

    def test_get_resource_invalid_id_returns_400(self):
        token = self._get_bearer_token()
        res = self._get_with_bearer(
            "/api/agentic/provisioning/resources/not-a-number",
            token=token,
        )
        assert res.status_code == 400

    def test_create_resource_missing_bearer_returns_401(self):
        res = self._post_api("/api/agentic/provisioning/resources")
        assert res.status_code == 401

    def test_create_resource_invalid_bearer_returns_401(self):
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token="pha_invalid_token",
        )
        assert res.status_code == 401

    def test_get_resource_missing_bearer_returns_401(self):
        res = self._get_api(f"/api/agentic/provisioning/resources/{self.team.id}")
        assert res.status_code == 401

    def test_create_resource_includes_personal_api_key(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        assert res.status_code == 200
        personal_api_key = res.json()["complete"]["access_configuration"]["personal_api_key"]
        assert personal_api_key.startswith("phx_")

    def test_create_resource_creates_pat_for_user(self):
        initial_count = PersonalAPIKey.objects.filter(user=self.user).count()
        token = self._get_bearer_token()
        self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        assert PersonalAPIKey.objects.filter(user=self.user).count() == initial_count + 1

    def test_create_resource_pat_label_defaults_to_team_name(self):
        token = self._get_bearer_token()
        self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        assert pat.label == self.team.name[:40]

    def test_create_resource_pat_narrowed_to_granted_token_scope(self):
        # The test bearer is granted only query:read; the PAT must not widen to the
        # full ceiling even when the app's grantable set is broader.
        token = self._get_bearer_token()
        app = self.partner
        app.scopes = ["insight:read", "query:read"]
        app.save(update_fields=["scopes"])
        self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        assert pat.scopes == ["query:read"]
        assert pat.scoped_teams == [self.team.id]
        assert pat.scoped_organizations == [str(self.team.organization_id)]
        assert pat.provisioned_by_id == app.id

    def test_create_resource_pat_excludes_optional_scopes_outside_grant(self):
        token = self._get_bearer_token()
        app = self.partner
        app.scopes = ["query:read"]
        app.optional_scopes = ["insight:read"]
        app.save(update_fields=["scopes", "optional_scopes"])
        self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        assert pat.scopes == ["query:read"]

    def test_create_resource_omits_pat_when_app_gate_off(self):
        token = self._get_bearer_token()
        app = self.partner
        app.update_provisioning(issues_personal_api_key=False)
        before = PersonalAPIKey.objects.filter(user=self.user).count()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        assert res.status_code == 200
        assert "personal_api_key" not in res.json()["complete"]["access_configuration"]
        assert PersonalAPIKey.objects.filter(user=self.user).count() == before

    @parameterized.expand([("gate_off", False), ("gate_on", True)])
    def test_create_provisioned_pat_gate(self, _name, gate_on):
        app = OAuthApplication.objects.create(
            name="Gate test app",
            client_id=f"gate_test_{gate_on}",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
            scopes=["insight:read"],
            _provisioning_config=provisioning_config(issues_personal_api_key=gate_on),
        )
        result = maybe_create_provisioned_pat(self.user, self.team, app, "insight:read")
        if gate_on:
            assert result is not None
            pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
            assert pat is not None
            assert pat.scopes == ["insight:read"]
        else:
            assert result is None
            assert not PersonalAPIKey.objects.filter(user=self.user).exists()

    def test_create_resource_does_not_delete_existing_pats(self):
        token = self._get_bearer_token()
        self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        first_pat = PersonalAPIKey.objects.filter(user=self.user, label=self.team.name[:40]).first()
        assert first_pat is not None

        self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        provisioning_pats = PersonalAPIKey.objects.filter(user=self.user, label=self.team.name[:40])
        assert provisioning_pats.count() == 2
        assert PersonalAPIKey.objects.filter(id=first_pat.id).exists()

    @parameterized.expand(
        [
            ("partner_label", "Acme Co", "Acme Co - "),
            ("empty_uses_team_name", "", "{team_name}"),
            ("whitespace_uses_team_name", "   ", "{team_name}"),
        ]
    )
    def test_create_resource_label_prefix_accepted(self, _name, label_prefix, expected_label_start_template):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"label_prefix": label_prefix},
            token=token,
        )
        assert res.status_code == 200
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        expected_label_start = expected_label_start_template.format(team_name=self.team.name)
        assert pat.label.startswith(expected_label_start)

    @parameterized.expand(
        [
            ("too_long", "a" * 26),
            ("control_char_newline", "Bad\nLabel"),
            ("control_char_tab", "Bad\tLabel"),
            ("bidi_override", "Bad‮Label"),
            ("zero_width_space", "Bad​Label"),
            ("non_string", 123),
        ]
    )
    def test_create_resource_label_prefix_rejected(self, _name, label_prefix):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"label_prefix": label_prefix},
            token=token,
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_label_prefix"

    def test_create_resource_label_combined_with_team_name_is_truncated_to_40_chars(self):
        token = self._get_bearer_token()
        long_team_name = "A" * 60
        self.team.name = long_team_name
        self.team.save()

        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"label_prefix": "PartnerX"},
            token=token,
        )
        assert res.status_code == 200
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        assert len(pat.label) == 40
        assert pat.label.startswith("PartnerX - ")

    def test_create_resource_with_project_id_creates_new_team(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_123"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        new_team_id = int(data["id"])
        assert new_team_id != self.team.id
        assert data["complete"]["access_configuration"]["api_key"] != self.team.api_token

    def test_create_resource_same_project_id_returns_same_team(self):
        token = self._get_bearer_token()
        res1 = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_456"},
            token=token,
        )
        res2 = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_456"},
            token=token,
        )
        assert res1.json()["id"] == res2.json()["id"]

    def test_create_resource_different_project_ids_create_different_teams(self):
        token = self._get_bearer_token()
        res1 = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_a"},
            token=token,
        )
        res2 = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_b"},
            token=token,
        )
        assert res1.json()["id"] != res2.json()["id"]

    def test_create_resource_with_project_id_adds_to_scoped_teams(self):
        token = self._get_bearer_token()
        self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_scope"},
            token=token,
        )
        access_token = OAuthAccessToken.objects.get(token=token)
        assert len(access_token.scoped_teams) == 2
        assert self.team.id in access_token.scoped_teams

    def test_create_resource_race_winner_in_different_org_does_not_leak_cross_org(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        from posthog.models.organization import Organization
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        other_org = Organization.objects.create(name="Foreign Org")
        foreign_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=other_org,
            name="Foreign project",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=foreign_team, defaults={"stripe_project_id": "proj_shared"}
        )

        original_update_or_create = TeamProvisioningConfig.objects.update_or_create
        calls: list[int] = []

        def raise_once_then_passthrough(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise IntegrityError
            return original_update_or_create(*args, **kwargs)

        token = self._get_bearer_token()
        with patch.object(TeamProvisioningConfig.objects, "update_or_create", side_effect=raise_once_then_passthrough):
            res = self._post_with_bearer(
                "/api/agentic/provisioning/resources",
                data={"project_id": "proj_shared"},
                token=token,
            )

        assert res.status_code == 409
        assert res.json()["error"]["code"] == "project_id_conflict"

        access_token = OAuthAccessToken.objects.get(token=token)
        assert foreign_team.id not in (access_token.scoped_teams or [])

    def test_create_resource_race_winner_in_same_org_returns_winner_and_syncs_scopes(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        winner_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Race winner",
        )

        project_id = "proj_race_same_org"
        token = self._get_bearer_token()
        access_token_app = OAuthAccessToken.objects.get(token=token).application
        original_update_or_create = TeamProvisioningConfig.objects.update_or_create
        raced: list[int] = []

        def race_then_raise(*args, **kwargs):
            defaults = kwargs.get("defaults", {})
            if "stripe_project_id" in defaults and not raced:
                raced.append(1)
                original_update_or_create(
                    team=winner_team,
                    defaults={"stripe_project_id": project_id, "application": access_token_app},
                )
                raise IntegrityError
            return original_update_or_create(*args, **kwargs)

        with patch.object(TeamProvisioningConfig.objects, "update_or_create", side_effect=race_then_raise):
            res = self._post_with_bearer(
                "/api/agentic/provisioning/resources",
                data={"project_id": project_id},
                token=token,
            )

        assert res.status_code == 200
        assert res.json()["id"] == str(winner_team.id)

        access_token = OAuthAccessToken.objects.get(token=token)
        assert winner_team.id in (access_token.scoped_teams or [])
        assert self.team.id in (access_token.scoped_teams or [])

    def test_create_resource_with_existing_project_id_adds_resolved_team_to_scoped_teams(self):
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        existing_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Pre-existing project",
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        TeamProvisioningConfig.objects.update_or_create(
            team=existing_team,
            defaults={"stripe_project_id": "proj_existing", "application": access_token.application},
        )
        assert access_token.scoped_teams == [self.team.id]

        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_existing"},
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["id"] == str(existing_team.id)

        access_token.refresh_from_db()
        assert existing_team.id in access_token.scoped_teams
        assert self.team.id in access_token.scoped_teams

    def test_create_resource_with_existing_project_id_rejects_when_user_lacks_team_access(self):
        from posthog.constants import AvailableFeature
        from posthog.models.organization import OrganizationMembership
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        from products.access_control.backend.models.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        restricted_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Restricted project",
        )

        token = self._get_bearer_token()
        access_token_obj = OAuthAccessToken.objects.get(token=token)
        TeamProvisioningConfig.objects.update_or_create(
            team=restricted_team,
            defaults={"stripe_project_id": "proj_restricted", "application": access_token_obj.application},
        )
        AccessControl.objects.create(
            team=restricted_team,
            access_level="none",
            resource="project",
            resource_id=str(restricted_team.id),
        )

        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_restricted"},
            token=token,
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

        access_token = OAuthAccessToken.objects.get(token=token)
        assert restricted_team.id not in (access_token.scoped_teams or [])

    def test_create_resource_with_existing_project_id_owned_by_other_partner_does_not_leak(self):
        # Same project_id but provisioned by a different OAuth application.
        # The current partner must not be able to resolve into the other partner's
        # team (which would otherwise hand back that team's api_token/PAT).
        from posthog.models.oauth import OAuthApplication
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        other_partner = OAuthApplication.objects.create(
            name="Other Partner",
            client_id="other_partner_client_id",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
        )
        other_partner_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Other partner project",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=other_partner_team,
            defaults={"stripe_project_id": "proj_shared_id", "application": other_partner},
        )

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert access_token.application_id != other_partner.id

        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_shared_id"},
            token=token,
        )
        # stripe_project_id is unique across all TPCs, so the create branch hits
        # IntegrityError and the race_winner lookup (also partner-bound) misses.
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "project_id_conflict"

        access_token.refresh_from_db()
        assert other_partner_team.id not in (access_token.scoped_teams or [])

    def test_create_resource_race_winner_rejects_when_user_lacks_team_access(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        from posthog.constants import AvailableFeature
        from posthog.models.organization import OrganizationMembership
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        from products.access_control.backend.models.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            MEMBERS_CAN_CREATE_PROJECTS_FEATURE,
            UNLIMITED_PROJECTS_FEATURE,
        ]
        self.organization.members_can_create_projects = True
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        restricted_team = Team.objects.create_with_data(
            initiating_user=self.user,
            organization=self.organization,
            name="Restricted race winner",
        )
        AccessControl.objects.create(
            team=restricted_team,
            access_level="none",
            resource="project",
            resource_id=str(restricted_team.id),
        )

        project_id = "proj_race_restricted"
        token = self._get_bearer_token()
        access_token_app = OAuthAccessToken.objects.get(token=token).application
        original_update_or_create = TeamProvisioningConfig.objects.update_or_create
        raced: list[int] = []

        def race_then_raise(*args, **kwargs):
            defaults = kwargs.get("defaults", {})
            if "stripe_project_id" in defaults and not raced:
                raced.append(1)
                original_update_or_create(
                    team=restricted_team,
                    defaults={"stripe_project_id": project_id, "application": access_token_app},
                )
                raise IntegrityError
            return original_update_or_create(*args, **kwargs)

        with patch.object(TeamProvisioningConfig.objects, "update_or_create", side_effect=race_then_raise):
            res = self._post_with_bearer(
                "/api/agentic/provisioning/resources",
                data={"project_id": project_id},
                token=token,
            )

        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

        access_token = OAuthAccessToken.objects.get(token=token)
        assert restricted_team.id not in (access_token.scoped_teams or [])

    def test_create_resource_without_project_id_returns_existing_team(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        assert res.json()["id"] == str(self.team.id)

    def test_create_resource_with_project_id_and_name(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={
                "project_id": "proj_named",
                "configuration": {"project_name": "My App"},
            },
            token=token,
        )
        assert res.status_code == 200
        new_team = Team.objects.get(id=int(res.json()["id"]))
        assert new_team.name == "My App"

    def test_create_resource_new_team_belongs_to_same_org(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"project_id": "proj_org"},
            token=token,
        )
        new_team = Team.objects.get(id=int(res.json()["id"]))
        assert new_team.organization_id == self.team.organization_id

    def test_get_resource_does_not_include_personal_api_key(self):
        token = self._get_bearer_token()
        res = self._get_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.status_code == 200
        assert "personal_api_key" not in res.json()["complete"]["access_configuration"]


class TestProvisioningResourceRemove(ProvisioningTestBase):
    @parameterized.expand([("same_user", False), ("other_org_member", True)])
    def test_remove_strips_team_from_sibling_tokens(self, _name: str, sibling_is_other_member: bool) -> None:
        # Removing a resource has to revoke the team from every live token
        # the partner holds, for any user. Otherwise a sibling bearer that still
        # has the team in scope can short-circuit past the auto-add guard and keep
        # operating on the removed team.
        from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        TeamProvisioningConfig.objects.update_or_create(
            team=self.team,
            defaults={"stripe_project_id": "proj_remove_me", "application": access_token.application},
        )

        sibling_user = (
            User.objects.create_and_join(
                organization=self.organization, email="teammate@example.com", password="testpass", first_name="Mate"
            )
            if sibling_is_other_member
            else access_token.user
        )
        sibling_at = OAuthAccessToken.objects.create(
            application=access_token.application,
            user=sibling_user,
            token="sibling_access_token_value",
            expires=access_token.expires,
            scope=access_token.scope,
            scoped_teams=[self.team.id, 99999],
        )
        sibling_rt = OAuthRefreshToken.objects.create(
            application=access_token.application,
            user=sibling_user,
            token="sibling_refresh_token_value",
            access_token=sibling_at,
            scoped_teams=[self.team.id, 99999],
        )
        orphan_rt = OAuthRefreshToken.objects.create(
            application=access_token.application,
            user=sibling_user,
            token="orphan_refresh_token_value",
            access_token=None,
            scoped_teams=[self.team.id],
        )
        rotated_rt = OAuthRefreshToken.objects.create(
            application=access_token.application,
            user=sibling_user,
            token="rotated_refresh_token_value",
            access_token=None,
            revoked=timezone.now(),
            scoped_teams=[self.team.id],
        )
        for _ in range(5):
            assert maybe_create_provisioned_pat(sibling_user, self.team, access_token.application, "query:read")
        unrestricted_key, fully_unrestricted_key, other_organization_key, team_in_other_organization_key = (
            PersonalAPIKey.objects.filter(provisioned_by=access_token.application)[:4]
        )
        other_organization_id = str(Organization.objects.create(name="Other org").id)
        PersonalAPIKey.objects.filter(id=unrestricted_key.id).update(scoped_teams=[])
        PersonalAPIKey.objects.filter(id=fully_unrestricted_key.id).update(scoped_teams=[], scoped_organizations=[])
        PersonalAPIKey.objects.filter(id=other_organization_key.id).update(
            scoped_teams=[], scoped_organizations=[other_organization_id]
        )
        PersonalAPIKey.objects.filter(id=team_in_other_organization_key.id).update(
            scoped_organizations=[other_organization_id]
        )
        own_key = mint_personal_api_key(
            sibling_user,
            label=self.team.name,
            scopes=["query:read"],
            teams=AccessibleTeams.for_user(sibling_user, [self.team.id]),
            organization_ids=[str(self.team.organization_id)],
        ).key

        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/remove",
            token=token,
        )
        assert res.status_code == 200, res.json()
        assert res.json()["status"] == "removed"

        sibling_at.refresh_from_db()
        sibling_rt.refresh_from_db()
        assert self.team.id not in (sibling_at.scoped_teams or [])
        assert self.team.id not in (sibling_rt.scoped_teams or [])
        assert not OAuthRefreshToken.objects.filter(pk__in=[orphan_rt.pk, rotated_rt.pk]).exists()
        assert not OAuthRefreshToken.objects.filter(application=access_token.application, scoped_teams=[]).exists()
        surviving_ids = set(PersonalAPIKey.objects.filter(user=sibling_user).values_list("id", flat=True))
        assert surviving_ids == {own_key.id, other_organization_key.id, team_in_other_organization_key.id}

    def test_remove_deletes_an_unrestricted_partner_key_whose_owner_cannot_access_the_project(self) -> None:
        token = self._get_bearer_token()
        partner_app = OAuthAccessToken.objects.get(token=token).application
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        teammate = User.objects.create_and_join(
            organization=self.organization,
            email="private-teammate@example.com",
            password="testpass",
            level=OrganizationMembership.Level.MEMBER,
        )
        assert maybe_create_provisioned_pat(teammate, other_team, partner_app, "query:read")
        partner_key = PersonalAPIKey.objects.get(user=teammate, provisioned_by=partner_app)
        PersonalAPIKey.objects.filter(id=partner_key.id).update(
            scoped_teams=[], scoped_organizations=[str(self.organization.id)]
        )
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )

        res = self._post_with_bearer(f"/api/agentic/provisioning/resources/{self.team.id}/remove", token=token)

        assert res.status_code == 200, res.json()
        assert not PersonalAPIKey.objects.filter(id=partner_key.id).exists()

    def test_remove_names_no_actor_in_another_organization_a_partner_key_reaches(self) -> None:
        token = self._get_bearer_token()
        partner_app = OAuthAccessToken.objects.get(token=token).application
        other_organization = Organization.objects.create(name="Other org")
        teammate = User.objects.create_and_join(
            organization=self.organization, email="teammate@example.com", password="testpass"
        )
        teammate.join(organization=other_organization)
        assert maybe_create_provisioned_pat(teammate, self.team, partner_app, "query:read")
        partner_key = PersonalAPIKey.objects.get(user=teammate, provisioned_by=partner_app)
        PersonalAPIKey.objects.filter(id=partner_key.id).update(
            scoped_teams=[], scoped_organizations=[str(self.organization.id), str(other_organization.id)]
        )

        res = self._post_with_bearer(f"/api/agentic/provisioning/resources/{self.team.id}/remove", token=token)

        assert res.status_code == 200, res.json()
        actor_per_organization = dict(
            ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=partner_key.id, activity="deleted").values_list(
                "organization_id", "user_id"
            )
        )
        assert actor_per_organization == {self.organization.id: self.user.id, other_organization.id: None}

    def test_remove_does_not_delete_other_partners_config(self):
        # The base team is in the caller's scope, but its config belongs to a
        # different partner. remove strips the caller's own scope but must leave
        # the other partner's provisioning mapping intact.
        from posthog.models.oauth import OAuthAccessToken, OAuthApplication
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        other_partner = OAuthApplication.objects.create(
            name="Other Partner",
            client_id="other_partner_remove_client_id",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
        )
        TeamProvisioningConfig.objects.update_or_create(
            team=self.team, defaults={"application": other_partner, "stripe_project_id": "proj_other_owner"}
        )

        token = self._get_bearer_token()
        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/remove",
            token=token,
        )
        assert res.status_code == 200, res.json()

        config = TeamProvisioningConfig.objects.get(team=self.team)
        assert config.application_id == other_partner.id

        # the caller's token only had this team in scope, so stripping it revokes the token
        assert not OAuthAccessToken.objects.filter(token=token).exists()

    def test_remove_keeps_mapping_and_scope_when_key_deletion_fails(self) -> None:
        from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        TeamProvisioningConfig.objects.update_or_create(
            team=self.team, defaults={"application": access_token.application}
        )

        with patch(
            "ee.api.agentic_provisioning.views.resources.delete_provisioned_pats",
            side_effect=RuntimeError("key deletion failed"),
        ):
            res = self._post_with_bearer(f"/api/agentic/provisioning/resources/{self.team.id}/remove", token=token)

        assert res.status_code == 500
        assert TeamProvisioningConfig.objects.filter(team=self.team).exists()
        access_token.refresh_from_db()
        assert self.team.id in access_token.scoped_teams


class TestCreateProvisionedPat(ProvisioningTestBase):
    def _minting_app(self) -> OAuthApplication:
        app = self.partner
        app.scopes = ["query:read"]
        app.save(update_fields=["scopes"])
        return app

    @parameterized.expand(
        [
            ("default_when_none", None, "{team_name}"),
            ("custom_adds_prefix", "My Partner", "My Partner - {team_name}"),
            ("empty_uses_team_name", "", "{team_name}"),
        ]
    )
    def test_label_prefix_resolution(self, _name, label_prefix, expected_label_template):
        api_key = maybe_create_provisioned_pat(
            self.user, self.team, self._minting_app(), "query:read", label_prefix=label_prefix
        )
        assert api_key is not None
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        assert pat.label == expected_label_template.format(team_name=self.team.name)[:40]

    def test_label_is_truncated_to_40_chars(self):
        self.team.name = "A" * 60
        self.team.save()
        maybe_create_provisioned_pat(
            self.user, self.team, self._minting_app(), "query:read", label_prefix="LongPartnerName"
        )
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        assert len(pat.label) == 40
        assert pat.label.startswith("LongPartnerName - ")

    @parameterized.expand([("token_refreshed_or_deleted", None), ("team_out_of_scope", [])])
    def test_rotation_with_a_bearer_that_no_longer_covers_the_team_ends_earlier_keys_and_mints_none(
        self, _name: str, remaining_scoped_teams: list[int] | None
    ) -> None:
        token = self._get_bearer_token()
        access_token = OAuthAccessToken.objects.get(token=token)
        assert maybe_create_provisioned_pat(self.user, self.team, self._minting_app(), "query:read")
        tokens = OAuthAccessToken.objects.filter(pk=access_token.pk)
        if remaining_scoped_teams is None:
            tokens.delete()
        else:
            tokens.update(scoped_teams=remaining_scoped_teams)

        api_key = maybe_create_provisioned_pat(
            self.user, self.team, self._minting_app(), "query:read", access_token=access_token, replace_existing=True
        )

        assert api_key is None
        assert not PersonalAPIKey.objects.filter(user=self.user, provisioned_by=self.partner).exists()

    def test_no_pat_when_ceiling_unseeded(self):
        # A flag-on app without a scope ceiling must not fall back to ["*"] or
        # mint an empty-scope key — skip the mint entirely.
        app = self.partner
        app.scopes = []
        app.save(update_fields=["scopes"])
        initial_count = PersonalAPIKey.objects.filter(user=self.user).count()
        assert maybe_create_provisioned_pat(self.user, self.team, app, "query:read") is None
        assert PersonalAPIKey.objects.filter(user=self.user).count() == initial_count
