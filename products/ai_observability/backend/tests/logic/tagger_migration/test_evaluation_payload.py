from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.ai_observability.evaluation_hog import run_hog_eval

from products.ai_observability.backend.hog import compile_ai_observability_hog
from products.ai_observability.backend.logic.tagger_migration.evaluation_payload import (
    hog_payload,
    llm_judge_payload,
    option_keys,
)
from products.ai_observability.backend.models.evaluation_configs import CategoricalOutputConfig
from products.ai_observability.backend.models.taggers import HogTaggerConfig, LLMTaggerConfig

GENERATION = {
    "event": "$ai_generation",
    "uuid": "generation-1",
    "distinct_id": "user-1",
    "properties": {
        "$ai_input": [{"role": "user", "content": "My invoice is wrong"}],
        "$ai_output_choices": [{"role": "assistant", "content": "Let me check"}],
    },
}


class TestTaggerEvaluationPayload(SimpleTestCase):
    @parameterized.expand(
        [
            ("slugs", ["Billing issue", "Feature request"], ["billing-issue", "feature-request"]),
            ("accents_and_symbols", ["Café / Bar!", "  spaced  out  "], ["cafe-bar", "spaced-out"]),
            ("repeated_slug", ["A-B", "a b", "A_B"], ["a-b", "a-b-2", "a-b-3"]),
            ("no_letters_or_digits", ["😀", "日本語"], ["tag-1", "tag-2"]),
            ("too_long", ["x" * 200, "x" * 200], ["x" * 128, "x" * 126 + "-2"]),
        ]
    )
    def test_option_keys_are_unique_valid_category_keys(
        self, _name: str, names: list[str], expected: list[str]
    ) -> None:
        keys = option_keys(names)

        assert keys == expected
        CategoricalOutputConfig.model_validate(
            {"options": [{"key": key, "label": name} for key, name in zip(keys, names)], "selection_mode": "multiple"}
        )

    @parameterized.expand(
        [
            ("exactly_one", 1, 1, "single", False, None),
            ("at_most_one", 0, 1, "single", True, "If no category applies, the criteria does not apply."),
            ("bounded", 1, 2, "multiple", False, "Select at least 1 and at most 2 categories."),
            ("unbounded", 0, None, "multiple", False, None),
        ]
    )
    def test_llm_tagger_limits_become_selection_mode_and_prompt(
        self,
        _name: str,
        min_tags: int,
        max_tags: int | None,
        selection_mode: str,
        allows_na: bool,
        limit_line: str | None,
    ) -> None:
        config = LLMTaggerConfig(
            prompt="Classify the user's request.",
            tags=[
                {"name": "Billing issue", "description": "Money, invoices or plans"},
                {"name": "Other"},
                {"name": "Bug"},
            ],
            min_tags=min_tags,
            max_tags=max_tags,
        )

        payload = llm_judge_payload(config)

        assert payload["output_config"] == {
            "options": [
                {"key": "billing-issue", "label": "Billing issue"},
                {"key": "other", "label": "Other"},
                {"key": "bug", "label": "Bug"},
            ],
            "selection_mode": selection_mode,
            "allows_na": allows_na,
        }
        expected_prompt = (
            "Classify the user's request.\n\nWhat each category means:\n- Billing issue: Money, invoices or plans"
        )
        if limit_line:
            expected_prompt += f"\n\n{limit_line}"
        assert payload["evaluation_config"] == {"prompt": expected_prompt, "include_media": False}

    @parameterized.expand(
        [
            (
                "list_with_unknown_and_repeated_tags",
                "return ['Billing issue', 'Billing issue', 'unknown']",
                ["billing-issue"],
            ),
            ("single_string", "return 'Other'", ["other"]),
            ("null", "return null", []),
            ("no_return", "print('nothing to tag')", []),
            ("not_a_list", "return 5", []),
            ("throws", "throw Error('bad input')", None),
            (
                "reads_the_input",
                "if (input ilike '%invoice%') { return ['Billing issue'] }\nreturn []",
                ["billing-issue"],
            ),
            (
                "reads_the_tags_list",
                "let out := []\nfor (let tag in tags) { if (tag == 'Other') { out := arrayPushBack(out, tag) } }\nreturn out",
                ["other"],
            ),
            ("indexes_the_sorted_tags_like_the_tagger_runtime", "return [tags[1]]", ["billing-issue"]),
            ("own_function_and_quotes", "fun pick(x) { return x }\nreturn [pick('it\\'s \"new\"')]", ["it-s-new"]),
        ]
    )
    def test_hog_tagger_code_returns_the_same_tags_as_category_keys(
        self, _name: str, source: str, expected: list[str] | None
    ) -> None:
        payload: dict[str, Any] = hog_payload(
            HogTaggerConfig(source=source, tags=[{"name": "Other"}, {"name": "Billing issue"}, {"name": 'it\'s "new"'}])
        )

        result = run_hog_eval(
            compile_ai_observability_hog(payload["evaluation_config"]["source"], "destination"),
            GENERATION,
            allows_na=payload["output_config"]["allows_na"],
            output_type="categorical",
            output_config=payload["output_config"],
        )

        assert result["error"] is None
        assert result.get("categories") == expected
        assert result["applicable"] is (expected is not None)

    def test_hog_tagger_without_a_tag_list_keeps_an_empty_tags_list_and_uses_the_tags_it_sent(self) -> None:
        payload: dict[str, Any] = hog_payload(
            HogTaggerConfig(
                source="return [length(tags) == 0 ? 'stage:a' : 'stage:b', true, null, 'true', 1, 'stage:new']"
            ),
            sent_tags=("None", "True", "stage:a", "stage:b"),
        )

        result = run_hog_eval(
            compile_ai_observability_hog(payload["evaluation_config"]["source"], "destination"),
            GENERATION,
            allows_na=True,
            output_type="categorical",
            output_config=payload["output_config"],
        )

        assert [option["label"] for option in payload["output_config"]["options"]] == [
            "None",
            "True",
            "stage:a",
            "stage:b",
        ]
        assert result.get("categories") == ["stage-a", "true", "none"]
