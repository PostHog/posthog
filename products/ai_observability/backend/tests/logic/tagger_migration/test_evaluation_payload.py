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
            ("slugs", ["Billing issue", "Feature request"], ["billing_issue", "feature_request"]),
            ("accents_and_symbols", ["Café / Bar!", "  spaced  out  "], ["cafe_bar", "spaced_out"]),
            ("repeated_slug", ["A-B", "a b", "A_B"], ["a_b", "a_b_2", "a_b_3"]),
            ("no_letters_or_digits", ["😀", "日本語"], ["tag_1", "tag_2"]),
            ("too_long", ["x" * 200, "x" * 200], ["x" * 128, "x" * 126 + "_2"]),
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
                {"key": "billing_issue", "label": "Billing issue"},
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
        assert payload["evaluation_config"] == {"prompt": expected_prompt}

    @parameterized.expand(
        [
            (
                "list_with_unknown_and_repeated_tags",
                "return ['Billing issue', 'Billing issue', 'unknown']",
                ["billing_issue"],
            ),
            ("single_string", "return 'Other'", ["other"]),
            ("null", "return null", []),
            ("no_return", "print('nothing to tag')", []),
            ("not_a_list", "return 5", []),
            (
                "reads_the_input",
                "if (input ilike '%invoice%') { return ['Billing issue'] }\nreturn []",
                ["billing_issue"],
            ),
            (
                "reads_the_tags_list",
                "let out := []\nfor (let tag in tags) { if (tag == 'Other') { out := arrayPushBack(out, tag) } }\nreturn out",
                ["other"],
            ),
            ("own_function_and_quotes", "fun pick(x) { return x }\nreturn [pick('it\\'s \"new\"')]", ["it_s_new"]),
        ]
    )
    def test_hog_tagger_code_returns_the_same_tags_as_category_keys(
        self, _name: str, source: str, expected: list[str]
    ) -> None:
        payload: dict[str, Any] = hog_payload(
            HogTaggerConfig(source=source, tags=[{"name": "Billing issue"}, {"name": "Other"}, {"name": 'it\'s "new"'}])
        )

        result = run_hog_eval(
            compile_ai_observability_hog(payload["evaluation_config"]["source"], "evaluation"),
            GENERATION,
            output_type="categorical",
            output_config=payload["output_config"],
        )

        assert result["error"] is None
        assert result["categories"] == expected
