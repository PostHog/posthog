from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from posthog.llm.system_one import ChoiceAnswer, SystemOneResult

from .match import suggest_emojis


class TestSuggestEmojis(SimpleTestCase):
    @patch("posthog.emoji_search.match.build_system_one_client")
    def test_jurassic_park_suggests_dinosaurs_and_rides_in_one_call(self, build_client) -> None:
        cache.clear()
        probabilities = {"dinosaurs": 0.48, "theme parks": 0.36, "none": 0.04}
        build_client.return_value.decide.return_value = SystemOneResult(
            model="jevk5-0.2",
            answers={"theme": ChoiceAnswer(choice="dinosaurs", confidence=0.8, probabilities=probabilities)},
            input_tokens=100,
        )

        suggestions = suggest_emojis("jurassic park", team_id=1)

        assert {suggestion.emoji for suggestion in suggestions} == {"🦖", "🦕", "🎢", "🎡"}
        assert build_client.return_value.decide.call_count == 1
        question = build_client.return_value.decide.call_args.kwargs["questions"]["theme"]
        assert len(question.criteria) == 16
        assert build_client.call_args.kwargs["timeout"] == 0.8
        assert suggest_emojis("jurassic park", team_id=1) == suggestions
        assert build_client.return_value.decide.call_count == 1
