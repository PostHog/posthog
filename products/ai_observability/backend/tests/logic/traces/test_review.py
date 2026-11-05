from decimal import Decimal

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.review import reviewer_name, score_display_value

OPTIONS = {"options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}]}


@parameterized.expand(
    [
        ("categorical labels in selection order", "categorical", OPTIONS, ["bad", "good"], None, None, "Bad, Good"),
        ("categorical key missing from the snapshot", "categorical", OPTIONS, ["gone"], None, None, "gone"),
        ("categorical empty selection", "categorical", OPTIONS, [], None, None, "Reviewed"),
        ("categorical malformed config", "categorical", None, ["good"], None, None, "good"),
        ("numeric trailing zeros", "numeric", {}, None, Decimal("4.500000"), None, "4.5"),
        ("numeric whole", "numeric", {}, None, Decimal("10.000000"), None, "10"),
        ("numeric hundred", "numeric", {}, None, Decimal("100.000000"), None, "100"),
        ("numeric negative", "numeric", {}, None, Decimal("-0.250000"), None, "-0.25"),
        ("numeric missing", "numeric", {}, None, None, None, ""),
        ("boolean true default", "boolean", {}, None, None, True, "Yes"),
        ("boolean false default", "boolean", {}, None, None, False, "No"),
        ("boolean custom labels", "boolean", {"true_label": "Pass", "false_label": "Fail"}, None, None, True, "Pass"),
        ("boolean null reads false", "boolean", {}, None, None, None, "No"),
    ]
)
def test_score_display_value(
    _name: str,
    kind: str,
    config: dict[str, object] | None,
    categorical_values: list[str] | None,
    numeric_value: Decimal | None,
    boolean_value: bool | None,
    expected: str,
) -> None:
    assert score_display_value(kind, config, categorical_values, numeric_value, boolean_value) == expected


@parameterized.expand(
    [
        ("first name wins", "Ada", "ada@example.com", "d1", "Ada"),
        ("email next", "", "ada@example.com", "d1", "ada@example.com"),
        ("distinct id last", "", "", "d1", "d1"),
        ("nothing", "", "", None, None),
    ]
)
def test_reviewer_name(_name: str, first_name: str, email: str, distinct_id: str | None, expected: str | None) -> None:
    assert reviewer_name(first_name, email, distinct_id) == expected
