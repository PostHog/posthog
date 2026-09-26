from collections.abc import Mapping
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.llm.system_one import NoulAnswer, Question, SystemOneRequestFailed, SystemOneResult
from posthog.llm.system_one_client import GATEWAY_MAX_QUESTIONS
from posthog.models import EventDefinition
from posthog.taxonomic_search_intent.contracts import EventMatch, EventMatchRequest
from posthog.taxonomic_search_intent.event_match import CORE_EVENT_CANDIDATES, _question, match_core_events

BUILD_CLIENT = "posthog.taxonomic_search_intent.event_match.build_system_one_client"
CAPTURE = "posthog.taxonomic_search_intent.event_match.capture_exception"
# Any past time works: the check only asks whether an event was ever seen.
SEEN_AT = datetime(2026, 1, 1, tzinfo=UTC)


LABEL_BY_INSTRUCTIONS = {
    _question(candidate).instructions: candidate.label for candidate in CORE_EVENT_CANDIDATES.values()
}


def _model_that_believes(probabilities: Mapping[str, float], failing_label: str | None = None) -> MagicMock:
    client = MagicMock()

    def decide(*, state: str, questions: Mapping[str, Question]) -> SystemOneResult:
        labels = {LABEL_BY_INSTRUCTIONS[question.instructions] for question in questions.values()}
        if failing_label in labels:
            raise SystemOneRequestFailed("The ai-gateway was not reached: ReadTimeout")
        answers = {
            question_id: NoulAnswer(probability=probabilities.get(LABEL_BY_INSTRUCTIONS[question.instructions], 0.01))
            for question_id, question in questions.items()
        }
        return SystemOneResult(model="jevk5-0.2", answers=answers, input_tokens=90)

    client.decide.side_effect = decide
    return client


class TestMatchCoreEvents(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        for name in ("$autocapture", "$rageclick", "$pageview", "$exception"):
            EventDefinition.objects.create(
                team=self.team, project_id=self.team.project_id, name=name, last_seen_at=SEEN_AT
            )
        # Defined but never seen, so it has no data to show.
        EventDefinition.objects.create(team=self.team, project_id=self.team.project_id, name="$screen")

    def _search(self, query: str, team_id: int | None = None) -> EventMatchRequest:
        return EventMatchRequest(team_id=team_id or self.team.id, project_id=self.team.project_id, query=query)

    @parameterized.expand(
        [
            ("too_short", "a"),
            ("email", "ada@example.com"),
            ("url", "https://example.com/pricing"),
            ("id", "user 12345678"),
            ("url_after_words", "visits https://example.com/reset?token=abc"),
        ]
    )
    def test_never_asks_the_model_about_values_or_unanswerable_searches(self, _name: str, query: str) -> None:
        with patch(BUILD_CLIENT) as build:
            assert match_core_events(self._search(query)) == []

        build.assert_not_called()

    def test_asks_about_every_core_event_within_the_gateway_limit(self) -> None:
        client = _model_that_believes({})
        with patch(BUILD_CLIENT, return_value=client):
            match_core_events(self._search("browser capture"))

        asked = [len(call.kwargs["questions"]) for call in client.decide.call_args_list]
        assert max(asked) <= GATEWAY_MAX_QUESTIONS
        assert sum(asked) == len(CORE_EVENT_CANDIDATES)
        assert "Search: browser capture" in client.decide.call_args.kwargs["state"]

    def test_suggests_the_likely_ingested_events_strongest_first(self) -> None:
        client = _model_that_believes(
            {
                "Rageclick": 0.75,
                "Autocapture": 0.95,
                # Likely, but the project never sent it, so a suggestion would lead to an empty insight.
                "Dead click": 0.9,
                "Pageview": 0.72,
                "Exception": 0.71,
                "Screen": 0.85,
            }
        )
        with patch(BUILD_CLIENT, return_value=client):
            matches = match_core_events(self._search("browser capture"))

        assert matches == [
            EventMatch(name="$autocapture", label="Autocapture", probability=0.95),
            EventMatch(name="$rageclick", label="Rageclick", probability=0.75),
            EventMatch(name="$pageview", label="Pageview", probability=0.72),
        ]

    @parameterized.expand([("same_team", False, 1), ("other_team", True, 2)])
    def test_the_same_search_is_answered_once_per_team(
        self, _name: str, other_team: bool, expected_requests: int
    ) -> None:
        second_team_id = self.team.id + 1 if other_team else None
        with patch(BUILD_CLIENT, return_value=_model_that_believes({"Autocapture": 0.95})) as build:
            match_core_events(self._search("browser capture"))
            match_core_events(self._search("  browser   capture ", team_id=second_team_id))

        assert build.call_count == expected_requests

    def test_keeps_the_answers_of_the_requests_that_succeed(self) -> None:
        late_event = list(CORE_EVENT_CANDIDATES)[-1]
        EventDefinition.objects.create(
            team=self.team, project_id=self.team.project_id, name=late_event, last_seen_at=SEEN_AT
        )
        client = _model_that_believes(
            {"Autocapture": 0.95, CORE_EVENT_CANDIDATES[late_event].label: 0.8}, failing_label="Autocapture"
        )
        requests_per_search = -(-len(CORE_EVENT_CANDIDATES) // GATEWAY_MAX_QUESTIONS)
        with patch(BUILD_CLIENT, return_value=client), patch(CAPTURE) as capture:
            matches = match_core_events(self._search("browser capture"))
            match_core_events(self._search("browser capture"))

        assert [match.name for match in matches] == [late_event]
        assert capture.call_count == 2
        # A partial answer is not cached, so the second search asks every request again.
        assert client.decide.call_count == 2 * requests_per_search

    def test_fails_when_every_request_fails(self) -> None:
        client = MagicMock()
        client.decide.side_effect = SystemOneRequestFailed("The ai-gateway was not reached: ReadTimeout")
        with patch(BUILD_CLIENT, return_value=client), patch(CAPTURE), self.assertRaises(SystemOneRequestFailed):
            match_core_events(self._search("browser capture"))
