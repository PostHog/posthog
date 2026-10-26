import pytest

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import MessageLink
from products.alerts_platform.backend.logic.rule_metadata import (
    MAX_LINK_URL_CHARS,
    MAX_RULE_LABELS,
    InvalidRuleMetadata,
    links,
    render_annotations,
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
    ]
)
def test_a_link_may_not_template_its_site(_name: str, value: str) -> None:
    with pytest.raises(InvalidRuleMetadata):
        validate_annotations({"runbook_url": value}, {"team"})


@parameterized.expand(
    [
        ("label", "summary", "{{ $labels.service }} is down", "checkout is down"),
        ("value", "summary", "{{$value}} errors", "312 errors"),
        ("label_the_group_lacks", "summary", "{{ $labels.region }} is down", " is down"),
        (
            "link_value_cannot_leave_the_path",
            "runbook_url",
            "https://r.example.com/{{ $labels.path }}",
            "https://r.example.com/a%2F..%3Fx%3D1",
        ),
        ("template_that_no_longer_validates", "summary", "{{ humanize $value }}", None),
    ]
)
def test_an_annotation_renders_from_its_group(_name: str, name: str, template: str, expected: str | None) -> None:
    rendered = render_annotations({name: template}, labels={"service": "checkout", "path": "a/..?x=1"}, value=312.0)

    assert rendered.get(name) == expected


def test_links_come_from_url_annotations_with_the_runbook_first() -> None:
    annotations = {
        "summary": "API errors",
        "alert_dashboard_url": "https://grafana.example.com/d/1",
        "too_long_url": "https://example.com/" + "q" * MAX_LINK_URL_CHARS,
        **{f"extra_{index}_url": f"https://example.com/{index}" for index in range(10)},
        "runbook_url": "https://runbooks.example.com/api",
    }

    found = links(annotations)

    assert found[:2] == (
        MessageLink(label="Runbook", url="https://runbooks.example.com/api"),
        MessageLink(label="Alert dashboard", url="https://grafana.example.com/d/1"),
    )
    assert len(found) == 5
    assert all(len(link.url) <= MAX_LINK_URL_CHARS for link in found)
