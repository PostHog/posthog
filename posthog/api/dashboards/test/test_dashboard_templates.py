from rest_framework import status

from posthog.models.dashboard_templates import DashboardTemplate
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.test.base import APIBaseTest


def assert_template_equals(received, expected):
    keys_to_check = [
        "template_name",
        "dashboard_description",
        "tags",
        "variables",
        "tiles",
        "dashboard_filters",
    ]

    for key in keys_to_check:
        assert received[key] == expected[key], f"key {key} failed, expected {expected[key]} but got {received[key]}"


def get_template_from_response(response, id):
    for template in response.json()["results"]:
        if template["id"] == str(id):
            return template
    return None


variable_template = {
    "template_name": "Sign up conversion template with variables",
    "dashboard_description": "Use this template to see how many users sign up after visiting your pricing page.",
    "dashboard_filters": {},
    "tiles": [
        {
            "name": "Website Unique Users (Total)",
            "type": "INSIGHT",
            "color": "blue",
            "filters": {
                "events": ["{VARIABLE_1}"],
                "compare": True,
                "display": "BoldNumber",
                "insight": "TRENDS",
                "interval": "day",
                "date_from": "-30d",
            },
            "layouts": {
                "sm": {"h": 5, "i": "21", "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "i": "21", "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 1},
            },
            "description": "Shows the number of unique users that use your app every day.",
        },
    ],
    "tags": ["popular"],
    "variables": [
        {
            "id": "VARIABLE_1",
            "name": "Page view on your website",
            "description": "The event that is triggered when a user visits a page on your site",
            "type": "event",
            "default": {"id": "$pageview", "math": "dau", "type": "events"},
            "required": True,
        },
        {
            "id": "VARIABLE_2",
            "name": "Sign up event",
            "description": "The event that is triggered when a user signs up",
            "type": "event",
            "default": {"id": "$autocapture", "math": "dau", "type": "events"},
            "required": False,
        },
    ],
}


class TestDashboardTemplates(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.user.is_staff = True
        self.user.save()

    def test_create_and_get_dashboard_template_with_tile(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        dashboard_template = DashboardTemplate.objects.get(id=response.json()["id"])
        assert dashboard_template.team_id == self.team.pk

        assert_template_equals(
            dashboard_template.__dict__,
            variable_template,
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert response.status_code == status.HTTP_200_OK, response

        assert_template_equals(
            get_template_from_response(response, dashboard_template.id),
            variable_template,
        )

        assert get_template_from_response(response, dashboard_template.id)["team_id"] == self.team.pk

    def test_staff_can_make_dashboard_template_public(self) -> None:
        assert self.team.pk is not None
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert response.json()["scope"] == "team"

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"scope": "global"},
        )

        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_updated_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_updated_response.status_code == status.HTTP_200_OK, get_updated_response

        assert get_updated_response.json()["results"][0]["scope"] == "global"

    def test_staff_can_make_dashboard_template_private(self) -> None:
        assert self.team.pk is not None
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        id = response.json()["id"]

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{id}",
            {"scope": "global"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_updated_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_updated_response.status_code == status.HTTP_200_OK, get_updated_response

        assert get_template_from_response(get_updated_response, id)["scope"] == "global"

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{id}",
            {"scope": "team"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_updated_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_updated_response.status_code == status.HTTP_200_OK, get_updated_response

        assert get_template_from_response(get_updated_response, id)["scope"] == "team"

    def test_non_staff_cannot_make_dashboard_template_public(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        self.user.is_staff = False
        self.user.save()

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"scope": "global"},
        )
        assert update_response.status_code == status.HTTP_403_FORBIDDEN, update_response

    def test_non_staff_cannot_edit_dashboard_template(self) -> None:
        default_template = DashboardTemplate.objects.all()[0]
        assert default_template.scope == "global"

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{default_template.id}",
            {"template_name": "Test name"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        self.user.is_staff = False
        self.user.save()

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{default_template.id}",
            {"template_name": "Test name"},
        )
        assert update_response.status_code == status.HTTP_403_FORBIDDEN, update_response

    def test_non_staff_can_get_public_dashboard_templates(self) -> None:
        assert DashboardTemplate.objects.count() == 2  # Default template
        assert self.team.pk is not None
        new_org = Organization.objects.create(name="Test Org 2")
        new_team = Team.objects.create(name="Test Team 2", organization=new_org)
        dashboard_template = DashboardTemplate.objects.create(
            team_id=new_team.pk,
            scope=DashboardTemplate.Scope.ONLY_TEAM,
            **variable_template,
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert response.status_code == status.HTTP_200_OK, response

        assert len(response.json()["results"]) == 1  # Only default template

        dashboard_template.scope = "global"
        dashboard_template.save()

        get_updated_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert get_updated_response.status_code == status.HTTP_200_OK, get_updated_response

        assert len(get_updated_response.json()["results"]) == 2
        assert_template_equals(
            get_template_from_response(get_updated_response, dashboard_template.id),
            variable_template,
        )

    def test_non_staff_user_cannot_create_dashboard(self) -> None:
        assert DashboardTemplate.objects.count() == 2  # default template
        self.user.is_staff = False
        self.user.save()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response

        assert DashboardTemplate.objects.count() == 2  # default template

    def test_get_dashboard_template_by_id(self) -> None:
        assert DashboardTemplate.objects.count() == 2  # default template
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == 3

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}")

        assert response.status_code == status.HTTP_200_OK, response

        assert_template_equals(
            response.json(),
            variable_template,
        )

    def test_delete_dashboard_template_by_id(self) -> None:
        assert DashboardTemplate.objects.count() == 2  # default template
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == 3
        dashboard_template = DashboardTemplate.objects.get(id=response.json()["id"])

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"deleted": True},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_response.status_code == status.HTTP_200_OK, get_response

        assert get_template_from_response(get_response, dashboard_template.id) is None
        assert len(get_response.json()["results"]) == 1  # Just original template

    def test_non_staff_user_cannot_delete_dashboard_template_by_id(self) -> None:
        assert DashboardTemplate.objects.count() == 2  # default template
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == 3

        self.user.is_staff = False
        self.user.save()

        patch_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"deleted": True},
        )
        assert patch_response.status_code == status.HTTP_403_FORBIDDEN, patch_response

        get_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_response.status_code == status.HTTP_200_OK, get_response

        assert len(get_response.json()["results"]) == 2  # Both templates

    def test_update_dashboard_template_by_id(self) -> None:
        assert DashboardTemplate.objects.count() == 2  # default template
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert DashboardTemplate.objects.count() == 3

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"template_name": "new name"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response
        assert update_response.json()["template_name"] == "new name"

    def test_dashboard_template_schema(self) -> None:
        dashboard_template_schema = {
            "type": "object",
            "required": [
                "template_name",
                "dashboard_description",
                "dashboard_filters",
                "tiles",
            ],
            "properties": {
                "id": {
                    "description": "The id of the dashboard template",
                    "type": "string",
                },
                "template_name": {
                    "description": "The name of the dashboard template",
                    "type": "string",
                },
                "team_id": {
                    "description": "The team this dashboard template belongs to",
                    "type": ["number", "null"],
                },
                "created_at": {
                    "description": "When the dashboard template was created",
                    "type": "string",
                },
                "image_url": {
                    "description": "The image of the dashboard template",
                    "type": ["string", "null"],
                },
                "dashboard_description": {
                    "description": "The description of the dashboard template",
                    "type": "string",
                },
                "dashboard_filters": {
                    "description": "The filters of the dashboard template",
                    "type": "object",
                },
                "tiles": {
                    "description": "The tiles of the dashboard template",
                    "type": "array",
                    "items": {"type": "object"},
                    "minItems": 1,
                },
                "variables": {
                    "description": "The variables of the dashboard template",
                    "anyOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "id",
                                    "name",
                                    "type",
                                    "default",
                                    "description",
                                    "required",
                                ],
                                "properties": {
                                    "id": {
                                        "description": "The id of the variable",
                                        "type": "string",
                                    },
                                    "name": {
                                        "description": "The name of the variable",
                                        "type": "string",
                                    },
                                    "type": {
                                        "description": "The type of the variable",
                                        "enum": ["event"],
                                    },
                                    "default": {
                                        "description": "The default value of the variable",
                                        "type": "object",
                                    },
                                    "description": {
                                        "description": "The description of the variable",
                                        "type": "string",
                                    },
                                    "required": {
                                        "description": "Whether the variable is required",
                                        "type": "boolean",
                                    },
                                },
                            },
                        },
                        {"type": "null"},
                    ],
                },
                "tags": {
                    "description": "The tags of the dashboard template",
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }

        response = self.client.get(
            f"/api/projects/{self.team.pk}/dashboard_templates/json_schema",
        )
        assert response.status_code == status.HTTP_200_OK

        assert response.json() == dashboard_template_schema
        assert response.headers["Cache-Control"] == "max-age=120"

    def test_cant_make_templates_without_teamid_private(self) -> None:
        """
        This test protects us from accidentally making the original default templates private
        And as they don't have a team_id, they can't be then be found to be made public again
        """
        assert DashboardTemplate.objects.count() == 2  # default template

        dashboard_template = DashboardTemplate.objects.all()[0]

        assert dashboard_template.scope == "global"
        assert dashboard_template.team_id is None

        # can't update the default template to be private
        response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{dashboard_template.id}",
            {"scope": "team"},
        )
        # unauthorized
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # check it's still global
        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["scope"] == "global"

    def test_filter_template_list_by_scope(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        id = response.json()["id"]

        self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{id}",
            {"scope": "feature_flag"},
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?scope=feature_flag")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0]["scope"] == "feature_flag"
