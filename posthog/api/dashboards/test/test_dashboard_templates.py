import json
from typing import Any, Dict, List
from unittest.mock import Mock, PropertyMock, patch

from rest_framework import status

from posthog.models.dashboard_templates import DashboardTemplate
from posthog.test.base import APIBaseTest


def assert_template_equals(received, expected):
    keys_to_check = ["template_name", "dashboard_description", "tags", "variables", "tiles", "dashboard_filters"]

    for key in keys_to_check:
        assert received[key] == expected[key], f"key {key} failed, expected {expected[key]} but got {received[key]}"


# github does not return the OG template
github_response_json: List[Dict] = [
    {
        "name": "Website traffic",
        "url": "a github url",
        "description": "The website analytics dashboard that PostHog uses",
        "verified": True,
        "maintainer": "official",
    },
]

expected_template_listing_json: List[Dict] = [
    {
        "name": "Product analytics",
        "url": None,
        "description": "The OG PostHog product analytics dashboard template",
        "verified": True,
        "maintainer": "official",
    },
    {
        "name": "Website traffic",
        "url": "a github url",
        "description": "The website analytics dashboard that PostHog uses",
        "verified": True,
        "maintainer": "official",
    },
]

updated_template_listing_json: List[Dict] = [
    {
        **expected_template_listing_json[1],
        "url": "https://github.com/PostHog/templates-repository/blob/a-new-commit-hash/dashboards/posthog-website-traffic.json",
    },
]

website_traffic_template_listing: Dict = {
    "template_name": "Website traffic",
    "dashboard_description": "",
    "dashboard_filters": {},
    "tiles": [
        {
            "name": "Website Unique Users (Total)",
            "type": "INSIGHT",
            "color": "blue",
            "filters": {
                "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
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
    "tags": [],
}

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

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_create_and_get_dashboard_template_with_tile(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        assert DashboardTemplate.objects.count() == 1
        assert DashboardTemplate.objects.filter(team_id__isnull=True).count() == 1

        assert_template_equals(
            DashboardTemplate.objects.first().__dict__,
            variable_template,
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert response.status_code == status.HTTP_200_OK, response

        assert_template_equals(
            response.json()["results"][0],
            variable_template,
        )

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_non_staff_user_cannot_create_dashboard(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        self.user.is_staff = False
        self.user.save()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response

        assert DashboardTemplate.objects.count() == 0

    def test_get_dashboard_template_by_id(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        assert DashboardTemplate.objects.count() == 1
        dashboardTemplate = DashboardTemplate.objects.first()
        assert dashboardTemplate is not None
        id = dashboardTemplate.id

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/{id}")

        assert response.status_code == status.HTTP_200_OK, response

        assert_template_equals(
            response.json(),
            variable_template,
        )

    def test_delete_dashboard_template_by_id(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        assert DashboardTemplate.objects.count() == 1

        dashboardTemplate = DashboardTemplate.objects.first()
        assert dashboardTemplate is not None
        id = dashboardTemplate.id

        response = self.client.patch(f"/api/projects/{self.team.pk}/dashboard_templates/{id}", {"deleted": True})

        assert response.status_code == status.HTTP_200_OK, response

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert response.status_code == status.HTTP_200_OK, response

        assert response.json()["results"] == [], response.json()

    def test_non_staff_user_cannot_delete_dashboard_template_by_id(self) -> None:

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        assert DashboardTemplate.objects.count() == 1
        dashboardTemplate = DashboardTemplate.objects.first()
        assert dashboardTemplate is not None
        id = dashboardTemplate.id

        self.user.is_staff = False
        self.user.save()

        response = self.client.patch(f"/api/projects/{self.team.pk}/dashboard_templates/{id}", {"deleted": True})

        assert response.status_code == status.HTTP_403_FORBIDDEN, response

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert response.status_code == status.HTTP_200_OK, response

        assert response.json()["results"] != [], response.json()

    def test_update_dashboard_template_by_id(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED

        assert DashboardTemplate.objects.count() == 1
        dashboardTemplate = DashboardTemplate.objects.first()
        assert dashboardTemplate is not None
        id = dashboardTemplate.id

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{id}",
            {"template_name": "new name"},
        )

        assert response.status_code == status.HTTP_200_OK, response

        assert DashboardTemplate.objects.count() == 1
        dashboardTemplate = DashboardTemplate.objects.first()
        assert dashboardTemplate is not None
        assert dashboardTemplate.template_name == "new name"

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_calls_to_github_and_returns_the_listing(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, github_response_json)

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        assert response.status_code == status.HTTP_200_OK, response

        expected_listing: List[Dict[str, Any]] = []
        for tl in expected_template_listing_json:
            expected_listing.append({**tl, "installed": tl["name"] == "Product analytics", "has_new_version": False})

        assert response.json() == expected_listing

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_can_install_from_github(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        assert DashboardTemplate.objects.count() == 0

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {"name": "Website traffic", "url": "a github url"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        patched_requests.assert_called_with("a github url")

        assert DashboardTemplate.objects.count() == 1

        # all now show as installed

        self._patch_request_get(patched_requests, github_response_json)

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        assert response.status_code == status.HTTP_200_OK, response
        assert len(response.json()) == 2

        expected_listing: List[Dict[str, Any]] = []
        for tl in expected_template_listing_json:
            expected_listing.append({**tl, "installed": True, "has_new_version": False})

        assert response.json() == expected_listing

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_non_staff_user_cannot_install_templates(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        assert DashboardTemplate.objects.count() == 0

        self.user.is_staff = False
        self.user.save()
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {"name": "Website traffic", "url": "a github url"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response

        assert DashboardTemplate.objects.count() == 0

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_dashboards_are_installed_with_no_team_id(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {"name": "Website traffic", "url": "a github url"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        patched_requests.assert_called_with("a github url")

        assert DashboardTemplate.objects.count() == 1
        assert DashboardTemplate.objects.filter(team_id__isnull=True).count() == 1

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_can_update_from_github(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        assert DashboardTemplate.objects.count() == 0

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {"name": "Website traffic", "url": "a github url", "tiles": website_traffic_template_listing["tiles"]},
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        patched_requests.assert_called_with("a github url")

        assert DashboardTemplate.objects.count() == 1
        assert DashboardTemplate.objects.first().tags == []  # type: ignore

        self._patch_request_get(patched_requests, updated_template_listing_json)

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        assert response.status_code == status.HTTP_200_OK, response
        assert [r["has_new_version"] for r in response.json()] == [False, True]

        self._patch_request_get(
            patched_requests,
            {
                **website_traffic_template_listing,
                "tags": ["updated"],
            },
        )

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {"name": "Website traffic", "url": "a github url"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        assert DashboardTemplate.objects.count() == 1
        assert DashboardTemplate.objects.first().tags == ["updated"]  # type: ignore

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_validation_that_names_have_to_match(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        assert DashboardTemplate.objects.count() == 0

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {"name": "this is never going to match", "url": "a github url"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        response_json = response.json()
        assert (
            response_json["detail"]
            == 'The requested template "this is never going to match" does not match the requested template URL which loaded the template "Website traffic"'
        )

    @staticmethod
    def _patch_request_get(patched_requests, json_response):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_text = PropertyMock(return_value=json.dumps(json_response))
        type(mock_response).text = mock_text
        mock_response.json.return_value = json_response
        patched_requests.return_value = mock_response

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
