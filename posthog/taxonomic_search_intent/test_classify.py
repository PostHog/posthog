import dataclasses

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.llm.system_one import ChoiceAnswer, SystemOneResult
from posthog.taxonomic_search_intent.classify import classify_search_intent
from posthog.taxonomic_search_intent.contracts import SearchIntent, SearchIntentRequest, SearchIntentSource
from posthog.taxonomic_search_intent.prompt import SEARCH_INTENT_PROMPT, SearchIntentPrompt

ALL_TABS = ("suggested_filters", "events", "event_properties", "person_properties", "pageview_urls", "email_addresses")


def _search(
    query: str, available: tuple[str, ...] = ALL_TABS, active: str = "events", team_id: int = 7
) -> SearchIntentRequest:
    return SearchIntentRequest(
        team_id=team_id, query=query, active_group_type=active, available_group_types=available, scene="Insight"
    )


BUILD_CLIENT = "posthog.taxonomic_search_intent.classify.build_system_one_client"


def _answer(choice: str, confidence: float) -> SystemOneResult:
    return SystemOneResult(
        model="jevk5-0.2",
        answers={"tab": ChoiceAnswer(choice=choice, confidence=confidence, probabilities={choice: confidence})},
        input_tokens=90,
    )


class TestClassifySearchIntent(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        build = patch(BUILD_CLIENT).start()
        self.addCleanup(patch.stopall)
        self.build = build
        self.decide = build.return_value.decide

    @parameterized.expand(
        [
            ("email_value", "ada@example.com", ALL_TABS, "email_addresses", SearchIntentSource.RULE),
            (
                "email_value_without_email_tab",
                "ada@example.com",
                ("events", "person_properties"),
                "person_properties",
                SearchIntentSource.RULE,
            ),
            ("partial_email", "ada@exa", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("url_value", "https://example.com/pricing", ALL_TABS, "pageview_urls", SearchIntentSource.RULE),
            ("path_value", "/pricing", ALL_TABS, "pageview_urls", SearchIntentSource.RULE),
            ("path_with_query", "/reset?token=abc", ALL_TABS, "pageview_urls", SearchIntentSource.RULE),
            (
                "path_without_url_tab",
                "/search?q=ada",
                ("events", "person_properties"),
                None,
                SearchIntentSource.SKIPPED,
            ),
            ("opaque_token", "sess_a1b2c3d4", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("key_value_pair", "token=abc", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("url_inside_word", "visits:https://example.com/reset", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("only_a_phone", "+1 (415) 555-2671", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("only_a_host", "example.com", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("spaced_key_value", "token = sk_live_abcdefghijklmnop", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("value_after_marker", "token= sk_live_abcdefghijklmnop", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("spaced_email", "ada @ example.com", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("email_split_at_domain", "ada@ example.com", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("too_short", "e", ALL_TABS, None, SearchIntentSource.SKIPPED),
            ("one_option_left", "email", ("events", "suggested_filters"), None, SearchIntentSource.SKIPPED),
        ]
    )
    def test_never_asks_the_model_about_values_or_unanswerable_searches(
        self, _name: str, query: str, available: tuple[str, ...], expected: str | None, source
    ) -> None:
        intent = classify_search_intent(_search(query, available))

        assert (intent.group_type, intent.source) == (expected, source)
        self.decide.assert_not_called()

    @parameterized.expand(
        [
            ("id_like", "user 12345678", "user <number>"),
            ("opaque_token_in_words", "session sess_a1b2c3d4", "session <id>"),
            ("partial_email_in_words", "emails from ada@exa", "emails from <email>"),
            ("url_after_words", "visits https://example.com/reset", "visits <url>"),
            ("path_after_words", "visits /reset?token=abc", "visits <path>"),
            ("wrapped_url", "visits (https://example.com/reset)", "visits <url>"),
            ("bare_host_url", "visits example.com/reset/abc", "visits <path>"),
            ("windows_path", "opened C:\\Users\\ada\\notes.txt", "opened <path>"),
            ("key_value_in_words", "campaign utm_source=newsletter", "campaign <value>"),
            ("formatted_phone", "call +1 (415) 555-2671", "call <number>"),
            ("local_phone", "call 555-2671 today", "call <number> today"),
            ("ip_address", "show 10.24.8.7", "show <ip>"),
            ("short_ip_address", "show 10.0.0.1", "show <ip>"),
            ("bare_host", "visits example.com", "visits <url>"),
            ("bare_host_with_port", "visits app.example.io:8080", "visits <url>"),
            ("dotted_property_reads", "user.plan is pro", "user.plan is pro"),
            ("small_numbers_read", "top 10 events in 2024", "top 10 events in 2024"),
        ]
    )
    def test_asks_the_model_with_values_replaced(self, _name: str, query: str, model_reads: str) -> None:
        self.decide.return_value = _answer("event_properties", 0.8)

        intent = classify_search_intent(_search(query))

        assert f"Search: {model_reads}\n" in self.decide.call_args.kwargs["state"] + "\n"
        assert intent.model_query == model_reads

    def test_offers_only_the_tabs_the_picker_shows(self) -> None:
        self.decide.return_value = _answer("person_properties", 0.9)

        intent = classify_search_intent(_search("email"))

        assert intent == SearchIntent(
            group_type="person_properties",
            confidence=0.9,
            is_confident=True,
            source=SearchIntentSource.MODEL,
            suggests_switch=True,
            model_query="email",
        )
        sent = self.decide.call_args.kwargs
        assert set(sent["questions"]["tab"].criteria) == {
            "events",
            "event_properties",
            "person_properties",
            "pageview_urls",
            "email_addresses",
        }
        assert "Search: email" in sent["state"]

    @parameterized.expand(
        [
            ("confident_other_tab", "person_properties", 0.9, "events", True),
            ("weak_answer", "person_properties", 0.3, "events", False),
            ("already_on_that_tab", "person_properties", 0.9, "person_properties", False),
            ("on_the_all_tab", "person_properties", 0.9, "suggested_filters", False),
        ]
    )
    def test_suggests_a_switch_only_for_a_confident_different_tab(
        self, _name: str, choice: str, confidence: float, active: str, expected: bool
    ) -> None:
        self.decide.return_value = _answer(choice, confidence)

        assert classify_search_intent(_search("email", active=active)).suggests_switch is expected

    def test_an_answer_outside_the_offered_tabs_is_dropped(self) -> None:
        self.decide.return_value = _answer("cohorts", 0.99)

        assert classify_search_intent(_search("paying users")).source == SearchIntentSource.SKIPPED

    def test_asks_with_the_given_prompt(self) -> None:
        self.decide.return_value = _answer("person_properties", 0.9)
        prompt = SearchIntentPrompt(
            instructions="Which tab?",
            options={"events": "An event.", "person_properties": "A person property."},
            confident_threshold=0.95,
        )

        intent = classify_search_intent(_search("email"), prompt=prompt)

        assert intent.is_confident is False
        question = self.decide.call_args.kwargs["questions"]["tab"]
        assert (question.instructions, question.criteria) == ("Which tab?", prompt.options)

    def test_model_change_recomputes_cached_answers(self) -> None:
        self.decide.return_value = _answer("events", 0.9)
        models = ["posthog/hogference/jevk5-fp8-0.2", "posthog/hogference/jeeves-0.1"]

        for model in models:
            with patch("posthog.taxonomic_search_intent.classify.DECISION_MODEL", model):
                classify_search_intent(_search("checkout"))

        assert [call.kwargs["model"] for call in self.build.call_args_list] == models

    @parameterized.expand(
        [
            ("same_team_and_prompt", 7, SEARCH_INTENT_PROMPT, 1),
            ("other_team", 8, SEARCH_INTENT_PROMPT, 2),
            ("new_wording", 7, dataclasses.replace(SEARCH_INTENT_PROMPT, instructions="Which tab?"), 2),
            ("new_threshold", 7, dataclasses.replace(SEARCH_INTENT_PROMPT, confident_threshold=0.9), 2),
        ]
    )
    def test_the_same_search_is_answered_once_per_team_and_prompt(
        self, _name: str, second_team: int, second_prompt: SearchIntentPrompt, expected_calls: int
    ) -> None:
        self.decide.return_value = _answer("event_properties", 0.8)

        classify_search_intent(_search("current url"), prompt=SEARCH_INTENT_PROMPT)
        classify_search_intent(_search("  current   url ", team_id=second_team), prompt=second_prompt)

        assert self.decide.call_count == expected_calls
