import json
from pathlib import Path

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from posthog.llm.system_one import ChoiceAnswer, SystemOneResult

from .match import build_emoji_questions, build_subgroup_questions, load_catalog, suggest_emojis


def answer_questions(questions, selected):
    answers = {}
    for question_id, question in questions.items():
        probabilities = dict.fromkeys(question.criteria, 0.01)
        probabilities["none"] = 0.05
        for key, description in question.criteria.items():
            if any(term in str(description) for term in selected):
                probabilities[key] = 0.6
        choice = max(probabilities, key=lambda key: probabilities[key])
        answers[question_id] = ChoiceAnswer(
            choice=choice, confidence=probabilities[choice], probabilities=probabilities
        )
    return SystemOneResult(model="jevk5-0.2", answers=answers, input_tokens=100)


class TestSuggestEmojis(SimpleTestCase):
    def test_every_picker_emoji_is_available_to_jev(self) -> None:
        catalog = load_catalog()
        assert len(catalog.emojis) == 1923
        root = Path(__file__).resolve().parents[2]
        frontend_version = json.loads((root / "frontend/package.json").read_text())["dependencies"]["emojibase-data"]
        catalog_version = json.loads(Path(__file__).with_name("catalog.json").read_text())["emojibase_version"]
        assert frontend_version == catalog_version
        subgroup_questions = build_subgroup_questions(catalog)
        assert len(subgroup_questions) <= 32
        assert {key for question in subgroup_questions.values() for key in question.criteria if key != "none"} == {
            f"s{subgroup}" for subgroup in catalog.subgroups
        }
        candidates: set[str] = set()
        for subgroup in catalog.subgroups:
            questions = build_emoji_questions(catalog, [subgroup])
            assert len(questions) <= 32
            for question in questions.values():
                assert len(question.criteria) <= 16
                candidates.update(key for key in question.criteria if key != "none")
        assert candidates == set(catalog.emojis)
        largest_subgroups = sorted(catalog.subgroups, key=lambda key: -len(catalog.subgroups[key].emoji_keys))[:3]
        assert len(build_emoji_questions(catalog, largest_subgroups)) <= 32

    @patch("posthog.emoji_search.match.build_system_one_client")
    def test_jurassic_park_suggests_dinosaurs_and_rides(self, build_client) -> None:
        cache.clear()

        def decide(*, state, questions):
            selected = (
                ("reptiles", "other places")
                if "subgroup" in next(iter(questions))
                else ("T-Rex", "sauropod", "roller coaster", "ferris wheel")
            )
            return answer_questions(questions, selected)

        build_client.return_value.decide.side_effect = decide
        suggestions = suggest_emojis("jurassic park", team_id=1)

        assert {suggestion.emoji for suggestion in suggestions} == {"🦖", "🦕", "🎢", "🎡"}
        assert build_client.return_value.decide.call_count == 2
        for call in build_client.return_value.decide.call_args_list:
            assert len(call.kwargs["questions"]) <= 32
        assert suggest_emojis("jurassic park", team_id=1) == suggestions
        assert build_client.return_value.decide.call_count == 2

    @patch("posthog.emoji_search.match.build_system_one_client")
    def test_unrelated_search_stops_after_subgroups(self, build_client) -> None:
        cache.clear()
        build_client.return_value.decide.side_effect = lambda *, state, questions: answer_questions(questions, ())

        assert suggest_emojis("made up place", team_id=2) == []
        assert build_client.return_value.decide.call_count == 1
