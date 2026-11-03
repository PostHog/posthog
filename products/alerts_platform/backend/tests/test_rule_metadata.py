import pytest

from parameterized import parameterized

from products.alerts_platform.backend.logic.rule_metadata import (
    MAX_RULE_LABELS,
    InvalidRuleMetadata,
    validate_annotations,
    validate_labels,
)


@parameterized.expand(
    [
        ("one_label", "{{ $labels.service_name }} is down", ["service_name"]),
        ("tight_spacing", "{{$labels.team}}", ["team"]),
        ("two_labels", "{{ $labels.team }}/{{ $labels.env }}", ["team", "env"]),
    ]
)
def test_a_template_needs_every_label_it_references(_name: str, value: str, referenced: list[str]) -> None:
    validate_annotations({"summary": value}, referenced)
    with pytest.raises(InvalidRuleMetadata):
        validate_annotations({"summary": value}, referenced[1:])


@parameterized.expand(
    [
        ("function", "{{ humanize $value }}"),
        ("control_flow", '{{ if eq $labels.team "a" }}a{{ end }}'),
        ("index_syntax", '{{ index $labels "team" }}'),
        ("unclosed", "{{ $labels.team is down"),
        ("unclosed_after_a_valid_one", "{{ $value }} then {{ humanize $value"),
    ]
)
def test_a_template_beyond_substitution_is_refused(_name: str, value: str) -> None:
    with pytest.raises(InvalidRuleMetadata):
        validate_annotations({"summary": value}, {"team"})


@parameterized.expand(
    [
        ("dotted_name", {"service.name": "api"}),
        ("leading_digit", {"1team": "api"}),
        ("reserved_prefix", {"posthog_team": "api"}),
        ("blank_value", {"team": " "}),
        ("unstorable_value", {"team": "a\x00b"}),
        ("unencodable_name", {"te\ud800am": "api"}),
        ("too_many", {f"label_{index}": "x" for index in range(MAX_RULE_LABELS + 1)}),
    ]
)
def test_an_invalid_label_is_refused(_name: str, labels: dict[str, str]) -> None:
    with pytest.raises(InvalidRuleMetadata):
        validate_labels(labels)


def test_a_link_may_template_its_path() -> None:
    validate_annotations({"runbook_url": "https://runbooks.example.com/{{ $labels.team }}"}, {"team"})


@parameterized.expand(
    [
        ("templated_scheme", "{{ $labels.team }}"),
        ("templated_host", "https://{{ $labels.team }}/runbook"),
        ("templated_subdomain", "https://{{ $labels.team }}.example.com/runbook"),
        ("backslash_for_a_host", "https://\\/{{ $labels.team }}"),
        ("credentials_before_the_host", "https://user@{{ $labels.team }}/runbook"),
    ]
)
def test_a_link_may_not_template_its_site(_name: str, value: str) -> None:
    with pytest.raises(InvalidRuleMetadata):
        validate_annotations({"runbook_url": value}, {"team"})
