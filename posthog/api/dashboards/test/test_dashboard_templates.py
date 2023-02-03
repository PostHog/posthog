import json
from typing import Dict
from unittest.mock import Mock, PropertyMock, patch

from rest_framework import status

from posthog.api.dashboards.dashboard_templates import og_template_listing_json
from posthog.models.dashboard_templates import DashboardTemplate
from posthog.test.base import APIBaseTest

website_template_json: Dict = {
    "name": "Website traffic",
    "url": "website-traffic-github-url",
    "description": "The website analytics dashboard that PostHog uses",
    "verified": True,
    "maintainer": "official",
}

updated_website_template_json: Dict = {
    **website_template_json,
    "url": "updated-website-traffic-github-url",
}

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


def mock_responses(*args, **kwargs) -> Mock:
    if args[0] == "https://raw.githubusercontent.com/PostHog/templates-repository/main/dashboards/dashboards.json":
        mock_response = Mock()
        mock_response.status_code = 200
        mock_text = PropertyMock(return_value=json.dumps([website_template_json]))
        type(mock_response).text = mock_text
        mock_response.json.return_value = [website_template_json]
        return mock_response
    elif args[0] == "website-traffic-github-url":
        mock_response = Mock()
        mock_response.status_code = 200
        mock_text = PropertyMock(return_value=json.dumps(website_traffic_template_listing))
        type(mock_response).text = mock_text
        mock_response.json.return_value = website_traffic_template_listing
        return mock_response
    else:
        raise Exception("Unexpected request to " + args[0])


def mock_updated_responses(*args, **kwargs) -> Mock:
    if args[0] == "https://raw.githubusercontent.com/PostHog/templates-repository/main/dashboards/dashboards.json":
        mock_response = Mock()
        mock_response.status_code = 200
        mock_text = PropertyMock(return_value=json.dumps([updated_website_template_json]))
        type(mock_response).text = mock_text
        mock_response.json.return_value = [updated_website_template_json]
        return mock_response
    elif args[0] == "updated-website-traffic-github-url":
        mock_response = Mock()
        mock_response.status_code = 200
        mock_text = PropertyMock(
            return_value=json.dumps({**website_traffic_template_listing, "tags": ["with", "tags"]})
        )
        type(mock_response).text = mock_text
        mock_response.json.return_value = {**website_traffic_template_listing, "tags": ["with", "tags"]}
        return mock_response
    else:
        raise Exception("Unexpected request to " + args[0])


class TestDashboardTemplates(APIBaseTest):
    @patch("posthog.api.dashboards.dashboard_templates.requests.get", side_effect=mock_responses)
    def test_repository_calls_to_github_and_returns_the_listing(self, _patched_requests) -> None:
        assert DashboardTemplate.objects.count() == 0

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response)

        assert response.json() == [og_template_listing_json, website_template_json]

        # we didn't install the OG template in the DB, but we did install the template loaded from repository
        assert list(DashboardTemplate.objects.values_list("template_name", flat=True)) == ["Website traffic"]

    @patch("posthog.api.dashboards.dashboard_templates.requests.get")
    def test_repository_can_update_from_github(self, patched_requests) -> None:
        patched_requests.side_effect = mock_responses

        assert DashboardTemplate.objects.count() == 0

        self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")

        assert DashboardTemplate.objects.count() == 1
        assert DashboardTemplate.objects.first().tags == []  # type: ignore

        patched_requests.side_effect = mock_updated_responses

        self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/repository")

        assert DashboardTemplate.objects.count() == 1
        assert DashboardTemplate.objects.first().tags == ["with", "tags"]  # type: ignore
