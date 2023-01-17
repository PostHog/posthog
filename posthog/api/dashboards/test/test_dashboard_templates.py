import json
from typing import Any, Dict, List
from unittest.mock import Mock, PropertyMock, patch

from rest_framework import status

from posthog.models.dashboard_templates import DashboardTemplate
from posthog.test.base import APIBaseTest

template_listing_json = [
    {
        "name": "Product analytics",
        "url": "https://github.com/PostHog/templates-repository/blob/33d8e4552afa24f12b93444bf8773eada89197cf/dashboards/posthog-product-analytics.json",
        "description": "The OG PostHog product analytics dashboard template",
        "verified": True,
        "maintainer": "official",
    },
    {
        "name": "Website traffic",
        "url": "https://github.com/PostHog/templates-repository/blob/532b9883cc142735a85b332f10de0c6ea4b1108c/dashboards/posthog-website-traffic.json",
        "description": "The website analytics dashboard that PostHog uses",
        "verified": True,
        "maintainer": "official",
    },
]

website_traffic_template_listing = {
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
    # other installed templates show as installed

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_calls_to_github_and_returns_the_listing(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, template_listing_json)

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        expected_listing: List[Dict[str, Any]] = []
        for tl in template_listing_json:
            expected_listing.append({**tl, "installed": tl["name"] == "Product analytics"})

        assert response.json() == expected_listing

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_can_install_from_github(self, patched_requests) -> None:
        self._patch_request_get(patched_requests, website_traffic_template_listing)

        assert DashboardTemplate.objects.count() == 0

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates", {"name": "Website traffic", "url": "a github url"}
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
            expected_listing.append({**tl, "installed": True})

        assert response.json() == expected_listing

    @staticmethod
    def _patch_request_get(patched_requests, json_response):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_text = PropertyMock(return_value=json.dumps(json_response))
        type(mock_response).text = mock_text
        mock_response.json.return_value = json_response
        patched_requests.return_value = mock_response
