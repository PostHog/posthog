import pytest

from products.ai_observability.backend.input_transformations import (
    EvaluationInputTransformation,
    apply_input_transformations,
    compile_input_transformations,
)


@pytest.mark.parametrize("transformation", [{"pattern": "secret"}, {"pattern": "secret", "replacement": ""}])
def test_empty_or_omitted_replacement_removes_matches(transformation: EvaluationInputTransformation) -> None:
    compiled = compile_input_transformations([transformation])

    assert apply_input_transformations("a secret value", compiled) == "a  value"


def test_transformations_run_in_order() -> None:
    compiled = compile_input_transformations(
        [
            {"pattern": "private", "replacement": "sensitive"},
            {"pattern": "sensitive", "replacement": "[removed]"},
        ]
    )

    assert apply_input_transformations("private data", compiled) == "[removed] data"


def test_replacement_text_is_literal() -> None:
    compiled = compile_input_transformations([{"pattern": "(secret)", "replacement": r"\1"}])

    assert apply_input_transformations("secret", compiled) == r"\1"
