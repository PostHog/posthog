from parameterized import parameterized

from products.ai_observability.backend.logic.message_normalizer.scope import Scope
from products.ai_observability.backend.logic.message_normalizer.values import Value


@parameterized.expand(
    [
        ("role field", {"role": "assistant"}, "user", "assistant"),
        ("known type alias", {"type": "human"}, "assistant", "user"),
        ("role field is lowercased", {"role": "Assistant"}, "user", "assistant"),
        ("no role", {"content": "hi"}, "assistant", "assistant"),
        ("bare string", "a bare string", "user", "user"),
        ("unknown type", {"type": "tool_call"}, "assistant", "assistant"),
    ]
)
def test_resolves_the_role_for_a_node(_name: str, value: Value, inherited: str, expected: str) -> None:
    assert Scope.for_node(value, inherited).role == expected


def test_with_input_swaps_the_value_but_keeps_the_resolved_role() -> None:
    parent = Scope.for_node({"role": "assistant", "items": [1]}, "user")
    child = parent.with_input({"nested": True})
    assert child.value == {"nested": True}
    assert child.role == "assistant"
