import json
from typing import Any, Dict, List
from unittest.mock import Mock, PropertyMock, patch

from rest_framework import status

from posthog.models.dashboard_templates import DashboardTemplate
from posthog.test.base import APIBaseTest

template_listing_json: List[Dict] = [
    {
        "name": "Product analytics",
        "url": "some url",
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
    template_listing_json[0],
    {
        **template_listing_json[1],
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


class TestDashboardTemplates(APIBaseTest):
    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_calls_to_github_and_returns_the_listing(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, template_listing_json)

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        expected_listing: List[Dict[str, Any]] = []
        for tl in template_listing_json:
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
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        patched_requests.assert_called_with("a github url")

        assert DashboardTemplate.objects.count() == 1

        # all now show as installed

        self._patch_request_get(patched_requests, template_listing_json)

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        assert len(response.json()) == 2

        expected_listing: List[Dict[str, Any]] = []
        for tl in template_listing_json:
            expected_listing.append({**tl, "installed": True, "has_new_version": False})

        assert response.json() == expected_listing

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_can_update_from_github(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        assert DashboardTemplate.objects.count() == 0

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {"name": "Website traffic", "url": "a github url"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        patched_requests.assert_called_with("a github url")

        assert DashboardTemplate.objects.count() == 1
        assert DashboardTemplate.objects.first().tags == []  # type: ignore

        self._patch_request_get(patched_requests, updated_template_listing_json)

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
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
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

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
        response_json = response.json()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response_json)
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
