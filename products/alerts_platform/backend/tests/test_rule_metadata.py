import pytest

from parameterized import parameterized

from products.alerts_platform.backend.facade.rule_metadata import (
    MAX_RULE_LABELS,
    InvalidRuleMetadata,
    referenced_labels,
    validate_annotations,
    validate_labels,
)


@parameterized.expand(
    [
        ("plain_text", "Checkout is down", []),
        ("one_label", "{{ $labels.service_name }} is down", ["service_name"]),
        ("tight_spacing", "{{$labels.team}}", ["team"]),
        ("value_only", "Errors at {{ $value }}", []),
        ("two_labels", "{{ $labels.team }}/{{ $labels.env }}", ["team", "env"]),
    ]
)
def test_templates_reference_labels_by_name(_name: str, value: str, expected: list[str]) -> None:
    assert referenced_labels("summary", value) == expected


@parameterized.expand(
    [
        ("function", "{{ humanize $value }}"),
        ("control_flow", '{{ if eq $labels.team "a" }}a{{ end }}'),
        ("index_syntax", '{{ index $labels "team" }}'),
    ]
)
def test_a_template_beyond_substitution_is_refused(_name: str, value: str) -> None:
    with pytest.raises(InvalidRuleMetadata):
        referenced_labels("summary", value)


@parameterized.expand(
    [
        ("dotted_name", {"service.name": "api"}),
        ("leading_digit", {"1team": "api"}),
        ("reserved_prefix", {"posthog_team": "api"}),
        ("blank_value", {"team": " "}),
        ("too_many", {f"label_{index}": "x" for index in range(MAX_RULE_LABELS + 1)}),
    ]
)
def test_an_invalid_label_is_refused(_name: str, labels: dict[str, str]) -> None:
    with pytest.raises(InvalidRuleMetadata):
        validate_labels(labels)


def test_a_link_may_template_its_path_but_not_its_scheme() -> None:
    validate_annotations({"runbook_url": "https://runbooks.example.com/{{ $labels.team }}"}, {"team"})
    with pytest.raises(InvalidRuleMetadata):
        validate_annotations({"runbook_url": "{{ $labels.team }}"}, {"team"})
