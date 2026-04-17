from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

MOCK_PATH = "posthog.api.insight_metadata.hit_openai"


def _make_query(source: dict) -> dict:
    return {"kind": "InsightVizNode", "source": source}


def _trends_query(**kwargs) -> dict:
    return _make_query({"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}], **kwargs})


class TestGenerateInsightMetadata(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.url = f"/api/projects/{self.team.id}/insights/generate_metadata/"

    @patch(MOCK_PATH)
    def test_returns_name_and_description(self, mock_openai):
        mock_openai.return_value = ('{"name": "Daily Pageviews", "description": "Tracks daily page views."}', 10, 20)
        response = self.client.post(self.url, {"query": _trends_query()}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Daily Pageviews"
        assert response.json()["description"] == "Tracks daily page views."

    def test_missing_query_returns_400(self):
        response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Missing" in response.json()["error"]

    @patch(MOCK_PATH, side_effect=Exception("LLM API error"))
    def test_llm_failure_returns_500(self, mock_openai):
        response = self.client.post(self.url, {"query": _trends_query()}, format="json")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed" in response.json()["error"]

    def test_ai_not_approved_returns_403(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        response = self.client.post(self.url, {"query": _trends_query()}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            (
                "trends_with_breakdown",
                _make_query(
                    {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                        "breakdownFilter": {"breakdown": "$browser"},
                    }
                ),
            ),
            (
                "funnel",
                _make_query(
                    {
                        "kind": "FunnelsQuery",
                        "series": [
                            {"kind": "EventsNode", "event": "signup"},
                            {"kind": "EventsNode", "event": "purchase"},
                        ],
                    }
                ),
            ),
            (
                "paths",
                _make_query(
                    {
                        "kind": "PathsQuery",
                        "pathsFilter": {"includeEventTypes": ["$pageview"]},
                    }
                ),
            ),
        ]
    )
    @patch(MOCK_PATH)
    def test_accepts_various_query_types(self, _name, query, mock_openai):
        mock_openai.return_value = ('{"name": "Test Name", "description": "Test description."}', 10, 20)
        response = self.client.post(self.url, {"query": query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Test Name"
        assert response.json()["description"] == "Test description."

    @patch(MOCK_PATH)
    def test_actors_query_returns_name_and_description(self, mock_openai):
        mock_openai.return_value = (
            '{"name": "Persons Who Performed Pageviews", "description": "List of persons who performed pageviews."}',
            10,
            20,
        )
        actors_query = {
            "kind": "ActorsQuery",
            "source": {
                "kind": "InsightActorsQuery",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                    "trendsFilter": {},
                    "filterTestAccounts": True,
                },
                "day": "2026-03-30T00:00:00Z",
                "series": 0,
                "includeRecordings": True,
            },
            "orderBy": ["event_count DESC, actor_id DESC"],
            "search": "",
        }
        response = self.client.post(self.url, {"query": actors_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Persons Who Performed Pageviews"
        call_args = mock_openai.call_args
        prompt_content = call_args[0][0][1]["content"]
        assert "ACTORS view" in prompt_content
        assert "Actor type: persons" in prompt_content
        assert "$pageview" in prompt_content

    def test_invalid_query_kind_returns_400(self):
        response = self.client.post(self.url, {"query": {"kind": "SomeRandomQuery"}}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch(MOCK_PATH)
    def test_actors_funnel_step_context_in_prompt(self, mock_openai):
        mock_openai.return_value = ('{"name": "Test", "description": "Test."}', 10, 20)
        actors_query = {
            "kind": "ActorsQuery",
            "source": {
                "kind": "FunnelsActorsQuery",
                "source": {
                    "kind": "FunnelsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": "$pageview", "name": "Pageview"},
                        {"kind": "EventsNode", "event": "$pageleave", "name": "$pageleave"},
                    ],
                    "funnelsFilter": {"funnelVizType": "steps"},
                    "filterTestAccounts": True,
                },
                "funnelStep": -2,
                "includeRecordings": True,
            },
            "orderBy": [],
            "search": "",
        }
        response = self.client.post(self.url, {"query": actors_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        assert "Dropped off at step 2" in prompt_content
        assert "$pageleave" in prompt_content

    @patch(MOCK_PATH)
    def test_actors_lifecycle_status_in_prompt(self, mock_openai):
        mock_openai.return_value = ('{"name": "Test", "description": "Test."}', 10, 20)
        actors_query = {
            "kind": "ActorsQuery",
            "source": {
                "kind": "InsightActorsQuery",
                "source": {
                    "kind": "LifecycleQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "lifecycleFilter": {},
                    "filterTestAccounts": True,
                },
                "day": "2026-03-26",
                "status": "resurrecting",
                "series": 0,
                "includeRecordings": True,
            },
            "orderBy": [],
            "search": "",
        }
        response = self.client.post(self.url, {"query": actors_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        assert "Lifecycle status: resurrecting" in prompt_content

    @patch(MOCK_PATH)
    def test_actors_narrows_to_selected_series(self, mock_openai):
        mock_openai.return_value = ('{"name": "Test", "description": "Test."}', 10, 20)
        actors_query = {
            "kind": "ActorsQuery",
            "source": {
                "kind": "InsightActorsQuery",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": "$pageview", "name": "Pageview"},
                        {"kind": "EventsNode", "event": "$pageleave", "name": "Pageleave"},
                    ],
                    "trendsFilter": {},
                    "filterTestAccounts": True,
                },
                "day": "2026-03-30T00:00:00Z",
                "series": 1,
                "includeRecordings": True,
            },
            "orderBy": [],
            "search": "",
        }
        response = self.client.post(self.url, {"query": actors_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        assert "Series: $pageleave" in prompt_content
        assert "Series: $pageview" not in prompt_content

    @patch(MOCK_PATH)
    def test_actors_breakdown_value_in_prompt(self, mock_openai):
        mock_openai.return_value = ('{"name": "Test", "description": "Test."}', 10, 20)
        actors_query = {
            "kind": "ActorsQuery",
            "source": {
                "kind": "InsightActorsQuery",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    "trendsFilter": {},
                    "filterTestAccounts": True,
                    "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event"},
                },
                "day": "2026-03-30T00:00:00Z",
                "series": 0,
                "breakdown": "Chrome",
                "includeRecordings": True,
            },
            "orderBy": [],
            "search": "",
        }
        response = self.client.post(self.url, {"query": actors_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        assert "$browser" in prompt_content
        assert "Chrome" in prompt_content

    @patch(MOCK_PATH)
    def test_events_query_returns_name_and_description(self, mock_openai):
        mock_openai.return_value = (
            '{"name": "Recent Events", "description": "Raw events from the last hour."}',
            10,
            20,
        )
        events_query = {
            "kind": "EventsQuery",
            "select": ["*", "event", "timestamp"],
            "orderBy": ["timestamp DESC"],
            "after": "-1h",
        }
        response = self.client.post(self.url, {"query": events_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Recent Events"
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        assert "EVENTS table" in prompt_content
        assert "All events" in prompt_content

    @patch(MOCK_PATH)
    def test_events_query_with_event_filter(self, mock_openai):
        mock_openai.return_value = (
            '{"name": "Pageview Events", "description": "Recent pageview events."}',
            10,
            20,
        )
        events_query = {
            "kind": "EventsQuery",
            "select": ["*", "event", "timestamp"],
            "event": "$pageview",
            "after": "-1h",
        }
        response = self.client.post(self.url, {"query": events_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        assert "Event: $pageview" in prompt_content

    @patch(MOCK_PATH)
    def test_events_query_with_property_filters(self, mock_openai):
        mock_openai.return_value = (
            '{"name": "Chrome Pageviews", "description": "Pageviews from Chrome browser."}',
            10,
            20,
        )
        events_query = {
            "kind": "EventsQuery",
            "select": ["*", "event", "timestamp"],
            "event": "$pageview",
            "properties": [
                {"type": "event", "key": "$browser", "operator": "exact", "value": "Chrome"},
            ],
            "after": "-1h",
        }
        response = self.client.post(self.url, {"query": events_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        assert "$browser" in prompt_content
        assert "Chrome" in prompt_content

    @patch(MOCK_PATH)
    def test_events_query_with_cohort_filter(self, mock_openai):
        mock_openai.return_value = (
            '{"name": "Pageviews Last Hour for Real Persons", "description": "Pageviews filtered to the Real persons cohort."}',
            10,
            20,
        )
        events_query = {
            "kind": "EventsQuery",
            "select": ["*", "event", "timestamp"],
            "event": "$pageview",
            "properties": [
                {"key": "$browser", "value": ["Chrome"], "operator": "exact", "type": "event"},
                {"key": "id", "value": 2, "type": "cohort", "operator": "in", "cohort_name": "Real persons"},
            ],
            "after": "-1h",
        }
        response = self.client.post(self.url, {"query": events_query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        assert "cohort 'Real persons'" in prompt_content
        assert "$browser" in prompt_content

    @parameterized.expand(
        [
            (
                "basic",
                {
                    "kind": "GroupsQuery",
                    "group_type_index": 0,
                    "select": ["group_key", "group_name"],
                },
                ["GROUPS list"],
            ),
            (
                "with_property_filter",
                {
                    "kind": "GroupsQuery",
                    "group_type_index": 3,
                    "select": ["group_name", "created_at"],
                    "properties": [
                        {
                            "key": "$virt_revenue",
                            "value": ["5555"],
                            "operator": "exact",
                            "type": "group",
                            "group_type_index": 3,
                        },
                    ],
                },
                ["GROUPS list", "$virt_revenue", "5555"],
            ),
            (
                "standalone_actors_with_search",
                {
                    "kind": "ActorsQuery",
                    "select": ["person_display_name -- Person", "id", "created_at"],
                    "search": "john",
                },
                ["person list", "Search: john"],
            ),
        ]
    )
    @patch(MOCK_PATH)
    def test_query_prompt_content(self, _name, query, expected_in_prompt, mock_openai):
        mock_openai.return_value = ('{"name": "Test name", "description": "Test description."}', 10, 20)
        response = self.client.post(self.url, {"query": query}, format="json")

        assert response.status_code == status.HTTP_200_OK
        prompt_content = mock_openai.call_args[0][0][1]["content"]
        for expected in expected_in_prompt:
            assert expected in prompt_content
