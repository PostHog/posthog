from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import ChoiceAnswer, SystemOneNotConfigured, SystemOneRequestFailed, SystemOneResult
from posthog.taxonomic_search_intent.prompt import BUNDLED_SEARCH_INTENT_PROMPT

ALL_TABS = ("suggested_filters", "events", "event_properties", "person_properties", "pageview_urls", "email_addresses")
BUILD_CLIENT = "posthog.taxonomic_search_intent.classify.build_system_one_client"
CURRENT_PROMPT = "posthog.taxonomic_search_intent.classify.current_search_intent_prompt"
FLAG_CHECK = "posthog.taxonomic_search_intent.classify.posthoganalytics.feature_enabled"


def _answer(choice: str, confidence: float) -> SystemOneResult:
    return SystemOneResult(
        model="jevk5-0.2",
        answers={"tab": ChoiceAnswer(choice=choice, confidence=confidence, probabilities={choice: confidence})},
        input_tokens=90,
    )


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSearchIntentEndpoint(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        patch(CURRENT_PROMPT, return_value=BUNDLED_SEARCH_INTENT_PROMPT).start()
        self.addCleanup(patch.stopall)

    def _post(self, body: dict | None = None):
        return self.client.post(
            f"/api/projects/{self.team.id}/taxonomic_search_intent/classify/",
            body or {"query": "email", "active_group_type": "events", "available_group_types": list(ALL_TABS)},
            format="json",
        )

    @patch(BUILD_CLIENT)
    @patch(FLAG_CHECK, return_value=True)
    def test_returns_the_tab_for_the_team(self, enabled, build) -> None:
        build.return_value.decide.return_value = _answer("person_properties", 0.9)

        response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "group_type": "person_properties",
            "confidence": 0.9,
            "is_confident": True,
            "suggests_switch": True,
            "method": "model",
            "prompt_version": None,
        }
        assert build.call_args.kwargs["distinct_id"] == team_distinct_id(self.team.id)
        assert enabled.call_args.args == ("taxonomic-filter-search-intent", str(self.user.distinct_id))

    @parameterized.expand(
        [
            ("disabled", "US", False, None, status.HTTP_404_NOT_FOUND),
            ("eu_cloud", "EU", True, None, status.HTTP_404_NOT_FOUND),
            ("self_hosted", None, True, None, status.HTTP_404_NOT_FOUND),
            ("not_configured", "US", True, SystemOneNotConfigured("no gateway"), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("unreachable", "US", True, SystemOneRequestFailed("timeout"), status.HTTP_503_SERVICE_UNAVAILABLE),
            (
                "refused",
                "US",
                True,
                SystemOneRequestFailed("boom", status_code=500),
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
        ]
    )
    def test_the_picker_gets_a_plain_failure_when_there_is_no_answer(
        self, _name, region, enabled, error, expected_status
    ) -> None:
        with (
            self.settings(CLOUD_DEPLOYMENT=region),
            patch(FLAG_CHECK, return_value=enabled),
            patch(BUILD_CLIENT, side_effect=error),
        ):
            response = self._post()

        assert response.status_code == expected_status

    def test_rejects_a_scene_that_is_not_an_id(self) -> None:
        response = self._post(
            {
                "query": "email",
                "active_group_type": "events",
                "available_group_types": ["events"],
                "scene": "https://example.com/?email=ada@example.com",
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
