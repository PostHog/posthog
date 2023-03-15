from rest_framework import status

from posthog.models.dashboard_templates import DashboardTemplate
from posthog.test.base import APIBaseTest


def assert_template_equals(received, expected):
    keys_to_check = ["template_name", "dashboard_description", "tags", "variables", "tiles", "dashboard_filters"]

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

    def test_non_staff_user_cannot_create_dashboard(self) -> None:
        assert DashboardTemplate.objects.count() == 1  # default template
        self.user.is_staff = False
        self.user.save()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response

        assert DashboardTemplate.objects.count() == 1  # default template

    def test_get_dashboard_template_by_id(self) -> None:
        assert DashboardTemplate.objects.count() == 1  # default template
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == 2

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}")

        assert response.status_code == status.HTTP_200_OK, response

        assert_template_equals(
            response.json(),
            variable_template,
        )

    def test_delete_dashboard_template_by_id(self) -> None:
        assert DashboardTemplate.objects.count() == 1  # default template
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == 2
        dashboard_template = DashboardTemplate.objects.get(id=response.json()["id"])

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}", {"deleted": True}
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_response.status_code == status.HTTP_200_OK, get_response

        assert get_template_from_response(get_response, dashboard_template.id) is None
        assert len(get_response.json()["results"]) == 1  # Just original template

    def test_non_staff_user_cannot_delete_dashboard_template_by_id(self) -> None:
        assert DashboardTemplate.objects.count() == 1  # default template
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == 2

        self.user.is_staff = False
        self.user.save()

        patch_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}", {"deleted": True}
        )
        assert patch_response.status_code == status.HTTP_403_FORBIDDEN, patch_response

        get_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_response.status_code == status.HTTP_200_OK, get_response

        assert len(get_response.json()["results"]) == 2  # Both templates

    def test_update_dashboard_template_by_id(self) -> None:
        assert DashboardTemplate.objects.count() == 1  # default template
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert DashboardTemplate.objects.count() == 2

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"template_name": "new name"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response
        assert update_response.json()["template_name"] == "new name"

    def test_dashboard_template_schema(self) -> None:
        dashboard_template_schema = {
            "type": "object",
            "required": ["template_name", "dashboard_description", "dashboard_filters", "tiles"],
            "properties": {
                "id": {"description": "The id of the dashboard template", "type": "string"},
                "template_name": {"description": "The name of the dashboard template", "type": "string"},
                "team_id": {"description": "The team this dashboard template belongs to", "type": "number"},
                "created_at": {"description": "When the dashboard template was created", "type": "string"},
                "image_url": {"description": "The image of the dashboard template", "type": ["string", "null"]},
                "dashboard_description": {"description": "The description of the dashboard template", "type": "string"},
                "dashboard_filters": {"description": "The filters of the dashboard template", "type": "object"},
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
                                "required": ["id", "name", "type", "default", "description", "required"],
                                "properties": {
                                    "id": {"description": "The id of the variable", "type": "string"},
                                    "name": {"description": "The name of the variable", "type": "string"},
                                    "type": {"description": "The type of the variable", "enum": ["event"]},
                                    "default": {"description": "The default value of the variable", "type": "object"},
                                    "description": {"description": "The description of the variable", "type": "string"},
                                    "required": {"description": "Whether the variable is required", "type": "boolean"},
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
