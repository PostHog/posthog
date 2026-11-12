import json
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.normalizer import RecipeNormalizer
from products.ai_observability.backend.logic.message_normalizer.values import MISSING, JsonValue

from .semantic import canonical


class ExpectedOutcome(TypedDict):
    messages: list[JsonValue]
    recognized: bool


class NormalizerCase(TypedDict):
    name: str
    call: Literal["normalizeMessage", "normalizeMessages"]
    input: JsonValue
    default_role: str
    tools: NotRequired[JsonValue]
    expected: ExpectedOutcome


CASES_PATH = Path(__file__).parents[4] / "shared" / "normalizer_cases.json"
CASES: list[NormalizerCase] = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


def test_the_case_file_holds_cases() -> None:
    assert len(CASES) > 0


@parameterized.expand([(case["name"], case) for case in CASES])
def test_normalizes_each_case(_name: str, case: NormalizerCase) -> None:
    normalizer = RecipeNormalizer()
    if case["call"] == "normalizeMessage":
        outcome = normalizer.normalize_message(case["input"], case["default_role"])
    else:
        outcome = normalizer.normalize_messages(case["input"], case["default_role"], case.get("tools", MISSING))
    assert outcome.recognized == case["expected"]["recognized"]
    assert canonical(list(outcome.messages)) == canonical(case["expected"]["messages"])
