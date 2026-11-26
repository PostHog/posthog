from parameterized import parameterized

from products.ai_observability.backend.logic.traces.node_labels import number_repeated_names


@parameterized.expand(
    [
        ("unique names are kept", ["plan", "search"], ["plan", "search"]),
        (
            "repeated names are numbered in order",
            ["agent", "openai.chat", "tool", "openai.chat"],
            ["agent", "openai.chat #1", "tool", "openai.chat #2"],
        ),
    ]
)
def test_number_repeated_names(_name: str, names: list[str], expected: list[str]) -> None:
    assert number_repeated_names(names) == expected
