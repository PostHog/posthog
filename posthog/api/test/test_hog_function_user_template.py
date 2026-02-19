from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team, User
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.hog_functions.hog_function_user_template import HogFunctionUserTemplate
from posthog.models.organization import OrganizationMembership

BASE_TEMPLATE_DATA = {
    "name": "My Template",
    "description": "A test template",
    "type": "destination",
    "hog": "fetch(inputs.url);",
    "inputs_schema": [],
}


def _make_template(team, created_by=None, **kwargs):
    data = {
        "name": "Fixture Template",
        "type": "destination",
        "hog": "fetch(inputs.url);",
        "team": team,
        "created_by": created_by,
    }
    data.update(kwargs)
    return HogFunctionUserTemplate.objects.create(**data)


def _make_hog_function(team, created_by=None, **kwargs):
    data = {
        "name": "My Function",
        "type": "destination",
        "hog": "fetch(inputs.url);",
        "team": team,
        "created_by": created_by,
    }
    data.update(kwargs)
    return HogFunction.objects.create(**data)


class TestHogFunctionUserTemplateAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/environments/{self.team.id}/hog_function_user_templates/"

    # -------------------------------------------------------------------------
    # CRUD – happy path
    # -------------------------------------------------------------------------

    def test_create_template_returns_201_with_all_fields(self):
        response = self.client.post(self.base_url, data=BASE_TEMPLATE_DATA)

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["name"] == "My Template"
        assert data["description"] == "A test template"
        assert data["type"] == "destination"
        assert data["hog"] == "fetch(inputs.url);"
        assert data["scope"] == HogFunctionUserTemplate.Scope.ONLY_TEAM
        assert data["inputs_schema"] == []
        assert data["filters"] is None
        assert data["masking"] is None
        assert data["tags"] == []
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_list_returns_only_own_team_templates(self):
        _make_template(self.team, name="Team A Template")
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        _make_template(other_team, name="Team B Template")

        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        names = [t["name"] for t in response.json()["results"]]
        assert "Team A Template" in names
        assert "Team B Template" not in names

    def test_retrieve_own_template(self):
        template = _make_template(self.team, name="Specific Template")

        response = self.client.get(f"{self.base_url}{template.id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == str(template.id)
        assert response.json()["name"] == "Specific Template"

    def test_update_template_with_patch(self):
        template = _make_template(self.team)

        response = self.client.patch(f"{self.base_url}{template.id}/", data={"name": "Updated Name"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["name"] == "Updated Name"
        template.refresh_from_db()
        assert template.name == "Updated Name"

    def test_delete_template(self):
        template = _make_template(self.team)

        response = self.client.delete(f"{self.base_url}{template.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not HogFunctionUserTemplate.objects.filter(id=template.id).exists()

    def test_list_is_ordered_by_updated_at_descending(self):
        _make_template(self.team, name="First")
        second = _make_template(self.team, name="Second")
        # Touch `second` so its updated_at is definitely later than `first`
        second.description = "touched"
        second.save()

        response = self.client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        names = [t["name"] for t in response.json()["results"]]
        assert names.index("Second") < names.index("First")

    # -------------------------------------------------------------------------
    # created_by
    # -------------------------------------------------------------------------

    def test_create_sets_created_by_to_requesting_user(self):
        response = self.client.post(self.base_url, data=BASE_TEMPLATE_DATA)

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["created_by"]["id"] == self.user.id

    def test_created_by_is_null_when_user_is_missing(self):
        template = _make_template(self.team, created_by=None)

        response = self.client.get(f"{self.base_url}{template.id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["created_by"] is None

    # -------------------------------------------------------------------------
    # Validation – parameterized missing/empty fields
    # -------------------------------------------------------------------------

    @parameterized.expand(
        [
            (
                "missing_name",
                {
                    **{k: v for k, v in BASE_TEMPLATE_DATA.items() if k != "name"},
                },
                "name",
            ),
            ("empty_name", {**BASE_TEMPLATE_DATA, "name": "   "}, "name"),
            (
                "missing_hog",
                {
                    **{k: v for k, v in BASE_TEMPLATE_DATA.items() if k != "hog"},
                },
                "hog",
            ),
            (
                "missing_type",
                {
                    **{k: v for k, v in BASE_TEMPLATE_DATA.items() if k != "type"},
                },
                "type",
            ),
        ]
    )
    def test_create_validation_error(self, _name, payload, expected_error_field):
        response = self.client.post(self.base_url, data=payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("attr") == expected_error_field

    def test_patch_with_empty_name_returns_400(self):
        template = _make_template(self.team)

        response = self.client.patch(f"{self.base_url}{template.id}/", data={"name": "   "})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("attr") == "name"

    def test_patch_without_name_does_not_raise_when_instance_already_has_name(self):
        template = _make_template(self.team, name="Existing Name")

        response = self.client.patch(f"{self.base_url}{template.id}/", data={"description": "new desc"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["name"] == "Existing Name"

    # -------------------------------------------------------------------------
    # Scope visibility
    # -------------------------------------------------------------------------

    def test_team_scoped_template_not_visible_to_other_team_in_same_org(self):
        _make_template(self.team, name="Team-only Template", scope=HogFunctionUserTemplate.Scope.ONLY_TEAM)
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        response = self.client.get(f"/api/environments/{other_team.id}/hog_function_user_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        names = [t["name"] for t in response.json()["results"]]
        assert "Team-only Template" not in names

    def test_org_scoped_template_visible_to_other_team_in_same_org(self):
        template = _make_template(self.team, name="Org Template", scope=HogFunctionUserTemplate.Scope.ORGANIZATION)
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        response = self.client.get(f"/api/environments/{other_team.id}/hog_function_user_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        ids = [t["id"] for t in response.json()["results"]]
        assert str(template.id) in ids

    def test_org_scoped_template_not_visible_to_team_in_different_org(self):
        _make_template(self.team, name="Org Template", scope=HogFunctionUserTemplate.Scope.ORGANIZATION)

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Org Team")
        other_user = User.objects.create_and_join(other_org, "other@example.com", "testpassword12345")
        self.client.force_login(other_user)

        response = self.client.get(f"/api/environments/{other_team.id}/hog_function_user_templates/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert not any(t["scope"] == "organization" for t in response.json()["results"])

    def test_retrieve_other_teams_team_scoped_template_returns_404(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        template = _make_template(other_team, name="Other Team Template", scope=HogFunctionUserTemplate.Scope.ONLY_TEAM)

        response = self.client.get(f"{self.base_url}{template.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    # -------------------------------------------------------------------------
    # Scope permissions (org-scoped requires admin)
    # -------------------------------------------------------------------------

    def test_org_admin_can_create_org_scoped_template(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        payload = {**BASE_TEMPLATE_DATA, "scope": "organization"}
        response = self.client.post(self.base_url, data=payload)

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["scope"] == "organization"

    def test_org_member_cannot_create_org_scoped_template(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        payload = {**BASE_TEMPLATE_DATA, "scope": "organization"}
        response = self.client.post(self.base_url, data=payload)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("attr") == "scope"

    def test_org_member_can_create_team_scoped_template(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        payload = {**BASE_TEMPLATE_DATA, "scope": "team"}
        response = self.client.post(self.base_url, data=payload)

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_org_member_cannot_patch_team_scoped_template_to_org_scope(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        template = _make_template(self.team, scope=HogFunctionUserTemplate.Scope.ONLY_TEAM)

        response = self.client.patch(f"{self.base_url}{template.id}/", data={"scope": "organization"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("attr") == "scope"

    # -------------------------------------------------------------------------
    # from_function action
    # -------------------------------------------------------------------------

    def test_from_function_creates_template_from_hog_function(self):
        hog_fn = _make_hog_function(
            self.team,
            created_by=self.user,
            name="Source Function",
            description="Fn description",
            type="destination",
            hog="fetch(inputs.url);",
            inputs_schema=[{"key": "url", "type": "string", "label": "URL", "required": True}],
        )

        response = self.client.post(f"{self.base_url}from_function/", data={"hog_function_id": str(hog_fn.id)})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["name"] == "Source Function"
        assert data["description"] == "Fn description"
        assert data["type"] == "destination"
        assert data["hog"] == "fetch(inputs.url);"
        assert data["inputs_schema"] == [{"key": "url", "type": "string", "label": "URL", "required": True}]

    def test_from_function_stores_template_in_database(self):
        hog_fn = _make_hog_function(self.team, created_by=self.user)

        self.client.post(f"{self.base_url}from_function/", data={"hog_function_id": str(hog_fn.id)})

        assert HogFunctionUserTemplate.objects.filter(team=self.team).exists()

    def test_from_function_allows_overriding_name_and_description(self):
        hog_fn = _make_hog_function(self.team, created_by=self.user, name="Original Name")

        response = self.client.post(
            f"{self.base_url}from_function/",
            data={
                "hog_function_id": str(hog_fn.id),
                "name": "Override Name",
                "description": "Override desc",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["name"] == "Override Name"
        assert response.json()["description"] == "Override desc"

    def test_from_function_defaults_scope_to_team(self):
        hog_fn = _make_hog_function(self.team, created_by=self.user)

        response = self.client.post(f"{self.base_url}from_function/", data={"hog_function_id": str(hog_fn.id)})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["scope"] == HogFunctionUserTemplate.Scope.ONLY_TEAM

    def test_from_function_missing_id_returns_400(self):
        response = self.client.post(f"{self.base_url}from_function/", data={})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("attr") == "hog_function_id"

    @parameterized.expand(
        [
            ("nonexistent_uuid", "00000000-0000-0000-0000-000000000000"),
        ]
    )
    def test_from_function_invalid_id_returns_400(self, _name, function_id):
        response = self.client.post(f"{self.base_url}from_function/", data={"hog_function_id": function_id})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("attr") == "hog_function_id"

    def test_from_function_deleted_function_returns_400(self):
        hog_fn = _make_hog_function(self.team, created_by=self.user, deleted=True)

        response = self.client.post(f"{self.base_url}from_function/", data={"hog_function_id": str(hog_fn.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("attr") == "hog_function_id"

    def test_from_function_other_teams_function_returns_400(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        hog_fn = _make_hog_function(other_team, created_by=self.user)

        response = self.client.post(f"{self.base_url}from_function/", data={"hog_function_id": str(hog_fn.id)})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json().get("attr") == "hog_function_id"

    def test_from_function_sets_created_by_to_requesting_user(self):
        hog_fn = _make_hog_function(self.team, created_by=self.user)

        response = self.client.post(f"{self.base_url}from_function/", data={"hog_function_id": str(hog_fn.id)})

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["created_by"]["id"] == self.user.id
