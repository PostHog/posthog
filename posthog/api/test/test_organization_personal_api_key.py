from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value


class TestOrganizationPersonalAPIKeyAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "organization_security_settings"}
        ]
        self.organization.save()

    def _create_key(self, user, **kwargs):
        return PersonalAPIKey.objects.create(
            user=user,
            label=kwargs.pop("label", "key"),
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=kwargs.pop("scopes", ["insight:read"]),
            **kwargs,
        )

    def _url(self, org=None):
        return f"/api/organizations/{(org or self.organization).id}/personal_api_keys/"

    def _set_level(self, level):
        self.organization_membership.level = level
        self.organization_membership.save()

    def test_admin_can_list_member_keys(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        member = User.objects.create_and_join(self.organization, "m@x.com", None)
        self._create_key(member, label="member-key")

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1

    def test_owner_can_list(self):
        self._set_level(OrganizationMembership.Level.OWNER)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK

    def test_plain_member_is_forbidden(self):
        self._set_level(OrganizationMembership.Level.MEMBER)
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_response_never_exposes_secret_or_label(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        self._create_key(self.user, label="super-secret-label")

        response = self.client.get(self._url())

        body = response.json()
        assert response.status_code == status.HTTP_200_OK
        row = body["results"][0]
        assert "label" not in row
        assert "secure_value" not in row
        assert "value" not in row
        assert set(row.keys()) == {
            "id",
            "owner",
            "mask_value",
            "scopes",
            "access_scope",
            "reaches_other_organizations",
            "last_used_at",
            "created_at",
        }
        assert row["owner"]["email"] == self.user.email

    def test_access_scope_values(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        self._create_key(self.user, label="unscoped")
        self._create_key(self.user, label="org", scoped_organizations=[str(self.organization.id)])
        self._create_key(self.user, label="team", scoped_teams=[self.team.id])

        results = self.client.get(self._url()).json()["results"]
        scope_types = {r["access_scope"]["type"] for r in results}

        assert scope_types == {"all", "organization", "projects"}
        projects_row = next(r for r in results if r["access_scope"]["type"] == "projects")
        assert projects_row["access_scope"]["projects"] == [{"id": self.team.id, "name": self.team.name}]

    @parameterized.expand(
        [
            ("unscoped_single_org", False, (), (), False),
            ("unscoped_multi_org", True, (), (), True),
            ("org_scoped_o_and_b", True, (), ("O", "B"), True),
            ("org_scoped_o_and_left_c", True, (), ("O", "C"), False),
            ("team_scoped_o_and_b", True, ("O", "B"), (), True),
            ("team_scoped_o_and_left_c", True, ("O", "C"), (), False),
            ("teams_o_b_orgs_o_only", True, ("O", "B"), ("O",), False),
        ]
    )
    def test_reaches_other_organizations(
        self, _name: str, owner_joins_b: bool, team_refs: tuple[str, ...], org_refs: tuple[str, ...], expected: bool
    ) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)
        org_b = Organization.objects.create(name="reach-probe-org-b-7f3c1d")
        team_b = Team.objects.create(organization=org_b, name="b-team")
        org_c = Organization.objects.create(name="reach-probe-org-c-7f3c1d")
        team_c = Team.objects.create(organization=org_c, name="c-team")
        owner = User.objects.create_and_join(self.organization, "owner@x.com", None)
        OrganizationMembership.objects.create(user=self.user, organization=org_b)
        if owner_joins_b:
            OrganizationMembership.objects.create(user=owner, organization=org_b)
        OrganizationMembership.objects.create(user=owner, organization=org_c).delete()
        teams = {"O": self.team.id, "B": team_b.id, "C": team_c.id}
        orgs = {"O": str(self.organization.id), "B": str(org_b.id), "C": str(org_c.id)}
        self._create_key(
            owner,
            scoped_teams=[teams[ref] for ref in team_refs] or None,
            scoped_organizations=[orgs[ref] for ref in org_refs] or None,
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["reaches_other_organizations"] is expected
        assert str(org_b.id).encode() not in response.content
        assert org_b.name.encode() not in response.content

    def test_excludes_other_org_keys(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        other_org = Organization.objects.create(name="other")
        Team.objects.create(organization=other_org, name="t")
        outsider = User.objects.create_and_join(other_org, "out@x.com", None)
        self._create_key(outsider, label="outsider")

        assert self.client.get(self._url()).json()["count"] == 0

    def test_requires_organization_security_settings_feature(self):
        self._set_level(OrganizationMembership.Level.ADMIN)
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert response.json()["code"] == "payment_required"
