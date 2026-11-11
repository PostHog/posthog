from pathlib import Path
from typing import NotRequired, TypedDict, cast

from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.compiler import compile_recipe
from products.ai_observability.backend.logic.message_normalizer.normalizer import RecipeNormalizer
from products.ai_observability.backend.logic.message_normalizer.values import JsonValue
from products.ai_observability.backend.logic.message_normalizer.yaml_loader import load_recipe_yaml

from .semantic import canonical


class ExampleCase(TypedDict):
    input: JsonValue
    default_role: NotRequired[str]
    expect: list[JsonValue]


class Example(TypedDict):
    title: str
    recipe: object
    cases: list[ExampleCase]


EXAMPLES_PATH = Path(__file__).parents[3] / "prompts" / "parser_recipe_examples.yaml"
EXAMPLES = cast(
    list[Example], cast(dict[str, object], load_recipe_yaml(EXAMPLES_PATH.read_text(encoding="utf-8")))["examples"]
)
CASES = [
    (f"{example['title']} #{case_index + 1}", example_index, case)
    for example_index, example in enumerate(EXAMPLES)
    for case_index, case in enumerate(example["cases"])
]


def test_documents_examples_with_cases() -> None:
    assert len(EXAMPLES) > 0
    assert all(len(example["cases"]) > 0 for example in EXAMPLES)


@parameterized.expand(CASES)
def test_produces_the_documented_messages(_name: str, example_index: int, case: ExampleCase) -> None:
    recipe = compile_recipe(EXAMPLES[example_index]["recipe"], f"example_{example_index}")
    outcome = RecipeNormalizer([recipe]).normalize_message(case["input"], case.get("default_role", "user"))
    assert outcome.recognized
    assert canonical(list(outcome.messages)) == canonical(case["expect"])
