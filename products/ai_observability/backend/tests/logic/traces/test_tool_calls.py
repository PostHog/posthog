from parameterized import parameterized

from products.ai_observability.backend.logic.traces.tool_calls import called_tool_names


@parameterized.expand(
    [
        ("a generation's tools, trimmed", "$ai_generation", " search, fetch ,, ", ("search", "fetch")),
        ("a span that carries tools", "$ai_span", "search, fetch", ()),
        ("a value that is not text", "$ai_generation", ["search"], ()),
    ]
)
def test_called_tool_names(_name: str, event: str, raw: object, expected: tuple[str, ...]) -> None:
    assert called_tool_names(event, raw) == expected
