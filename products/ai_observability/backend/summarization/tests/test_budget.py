from parameterized import parameterized

from products.ai_observability.backend.summarization.budget import (
    MODEL_CONTEXT_TOKENS,
    RESERVED_TOKENS,
    bounded_text_repr,
    text_repr_budget,
)
from products.ai_observability.backend.summarization.constants import DEFAULT_MODEL_OPENAI
from products.ai_observability.backend.summarization.models import OpenAIModel


class TestTextReprBudget:
    @parameterized.expand([(model,) for model in OpenAIModel])
    def test_every_supported_model_has_a_budget_inside_its_window(self, model: OpenAIModel):
        assert text_repr_budget(model) < MODEL_CONTEXT_TOKENS[model]

    def test_unrecognized_model_gets_no_more_than_the_smallest_window(self):
        assert text_repr_budget("gpt-9-imaginary") <= min(MODEL_CONTEXT_TOKENS.values()) - RESERVED_TOKENS

    @parameterized.expand([("empty", ""), ("none", None)])
    def test_unspecified_model_gets_the_default_model_budget(self, _name, model):
        assert text_repr_budget(model) == text_repr_budget(DEFAULT_MODEL_OPENAI)

    def test_a_narrow_window_model_gets_a_smaller_budget_than_a_wide_one(self):
        assert text_repr_budget(OpenAIModel.GPT_4O) < text_repr_budget(OpenAIModel.GPT_4_1_MINI)


class TestBoundedTextRepr:
    def test_text_within_budget_is_returned_unchanged(self):
        text = "L1: hello\nL2: world"
        assert bounded_text_repr(text, budget=1000) == text

    @parameterized.expand(
        [
            ("one_long_line", "L1: " + "x" * 5000),
            ("many_lines", "\n".join(f"L{i}: {'x' * 100}" for i in range(200))),
        ]
    )
    def test_oversized_text_is_reduced_to_the_budget(self, _name, text):
        assert len(bounded_text_repr(text, budget=500)) <= 500
