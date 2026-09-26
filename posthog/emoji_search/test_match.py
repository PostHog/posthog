import json
from dataclasses import replace
from pathlib import Path

import pytest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from posthog.llm.system_one import ChoiceAnswer, SystemOneResult

from .match import _ranked_probabilities, build_emoji_questions, build_subgroup_questions, load_catalog, suggest_emojis


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
    def test_rank_scores_against_each_questions_none_option(self) -> None:
        answers = {
            "first": ChoiceAnswer(choice="a", confidence=0.6, probabilities={"a": 0.6, "none": 0.4}),
            "second": ChoiceAnswer(choice="b", confidence=0.3, probabilities={"b": 0.3, "none": 0.1}),
            "third": ChoiceAnswer(choice="c", confidence=0.06, probabilities={"c": 0.06, "none": 0.02}),
            "tie": ChoiceAnswer(choice="none", confidence=0.5, probabilities={"d": 0.5, "none": 0.5}),
        }

        scores = _ranked_probabilities(answers, {"a", "b", "c", "d"})

        assert scores["a"] == 0.6
        assert scores["b"] == pytest.approx(0.75)
        assert scores["c"] == pytest.approx(0.75)
        assert "d" not in scores

    @patch("posthog.emoji_search.match.build_system_one_client")
    def test_cache_errors_do_not_discard_model_results(self, build_client) -> None:
        cache.clear()

        def decide(*, state, questions):
            selected = ("reptiles",) if "subgroup" in next(iter(questions)) else ("T-Rex",)
            return answer_questions(questions, selected)

        build_client.return_value.decide.side_effect = decide
        for cache_method in ("get", "set"):
            with self.subTest(cache_method=cache_method):
                with patch(f"posthog.emoji_search.match.cache.{cache_method}", side_effect=ConnectionError):
                    assert [suggestion.emoji for suggestion in suggest_emojis("jurassic park", team_id=1)] == ["🦖"]
                cache.clear()

    @patch("posthog.emoji_search.match.build_system_one_client")
    def test_case_distinct_queries_have_separate_cached_results(self, build_client) -> None:
        cache.clear()
        build_client.return_value.decide.side_effect = lambda *, state, questions: answer_questions(questions, ())

        suggest_emojis("Polish", team_id=4)
        suggest_emojis("polish", team_id=4)

        assert [call.kwargs["state"]["emoji_search"] for call in build_client.return_value.decide.call_args_list] == [
            "Polish",
            "polish",
        ]

    @patch("posthog.emoji_search.match.build_system_one_client")
    def test_catalog_change_invalidates_cached_results(self, build_client) -> None:
        cache.clear()
        catalog = load_catalog()
        build_client.return_value.decide.side_effect = lambda *, state, questions: answer_questions(questions, ())

        with patch(
            "posthog.emoji_search.match.load_catalog", side_effect=[catalog, replace(catalog, fingerprint="updated")]
        ):
            suggest_emojis("made up place", team_id=4)
            suggest_emojis("made up place", team_id=4)

        assert build_client.return_value.decide.call_count == 2

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

    @patch("posthog.emoji_search.match.build_system_one_client")
    def test_five_largest_subgroups_are_searched_within_request_limit(self, build_client) -> None:
        cache.clear()
        catalog = load_catalog()
        largest_subgroups = sorted(catalog.subgroups, key=lambda key: -len(catalog.subgroups[key].emoji_keys))[:5]
        selected_labels = {catalog.subgroups[key].label for key in largest_subgroups}

        def decide(*, state, questions):
            if "subgroup" in next(iter(questions)):
                answers = {}
                for question_id, question in questions.items():
                    probabilities = dict.fromkeys(question.criteria, 0.01)
                    probabilities["none"] = 0.05
                    for key, description in question.criteria.items():
                        if any(str(description).startswith(label + ":") for label in selected_labels):
                            probabilities[key] = 0.6
                    choice = max(probabilities, key=lambda key: probabilities[key])
                    answers[question_id] = ChoiceAnswer(
                        choice=choice, confidence=probabilities[choice], probabilities=probabilities
                    )
                return SystemOneResult(model="jevk5-0.2", answers=answers, input_tokens=100)
            return answer_questions(questions, ())

        build_client.return_value.decide.side_effect = decide
        suggest_emojis("five largest groups", team_id=3)

        calls = build_client.return_value.decide.call_args_list
        assert len(calls) == 3
        assert all(len(call.kwargs["questions"]) <= 32 for call in calls)
        searched_emojis = {
            key for call in calls[1:] for question in call.kwargs["questions"].values() for key in question.criteria
        }
        assert searched_emojis - {"none"} == {
            key for subgroup in largest_subgroups for key in catalog.subgroups[subgroup].emoji_keys
        }

    @patch("posthog.emoji_search.match.build_system_one_client")
    def test_jurassic_park_suggests_dinosaurs_and_rides(self, build_client) -> None:
        cache.clear()

        def decide(*, state, questions):
            selected = (
                ("reptiles", "other places")
                if "subgroup" in next(iter(questions))
                else ("T-Rex", "sauropod", "roller coaster", "ferris wheel", "carousel horse")
            )
            return answer_questions(questions, selected)

        build_client.return_value.decide.side_effect = decide
        suggestions = suggest_emojis("jurassic park", team_id=1)

        assert {suggestion.emoji for suggestion in suggestions} == {"🦖", "🦕", "🎢", "🎡", "🎠"}
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
