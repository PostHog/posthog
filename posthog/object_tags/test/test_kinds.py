from parameterized import parameterized

from posthog.object_tags.kinds import (
    OBJECT_KIND_ALIASES,
    OBJECT_KINDS,
    object_web_path,
    parse_object_url,
    resolve_object_kind,
)

PROJECT = "https://us.posthog.com/project/2"
HOGQL_NODE = "%7B%22kind%22%3A%22DataVisualizationNode%22%2C%22source%22%3A%7B%22kind%22%3A%22HogQLQuery%22%2C%22query%22%3A%22SELECT%201%22%7D%7D"


def test_registry_is_internally_consistent():
    for alias, kind in OBJECT_KIND_ALIASES.items():
        assert kind in OBJECT_KINDS, f"alias {alias!r} points at unregistered kind {kind!r}"
        assert alias not in OBJECT_KINDS, f"alias {alias!r} shadows a registered kind"
    for name, spec in OBJECT_KINDS.items():
        if spec.path_template is not None:
            assert "{id}" in spec.path_template, f"kind {name!r} template has no {{id}} placeholder"


def test_id_pattern_guards_paths():
    flag = resolve_object_kind("feature_flag")
    assert flag is not None
    assert object_web_path(flag, "42") == "/feature_flags/42"
    assert object_web_path(flag, "my-flag-key") is None

    event = OBJECT_KINDS["event"]
    assert object_web_path(event, "0192D9EA-52AA-0000-8CCC-1A25E2E7DBBC") is not None
    assert object_web_path(event, "$pageview") is None


@parameterized.expand(
    [
        (f"{PROJECT}/insights/9pQx3", ("insight", "9pQx3")),
        (f"{PROJECT}/insights/9pQx3/edit?x=1", ("insight", "9pQx3")),
        (f"{PROJECT}/i/9pQx3", ("insight", "9pQx3")),
        ("https://us.posthog.com/insights/9pQx3", ("insight", "9pQx3")),
        ("https://app.posthog.com/project/2/insights/9pQx3", ("insight", "9pQx3")),
        (f"{PROJECT}/sql?open_query=SELECT%20count()%20FROM%20events", ("hogql", "SELECT count() FROM events")),
        (f"{PROJECT}/sql?open_query=SELECT+1", ("hogql", "SELECT 1")),
        (f"{PROJECT}/sql?open_query={HOGQL_NODE}", ("hogql", "SELECT 1")),
        (f"{PROJECT}/insights/new#q={HOGQL_NODE}", ("hogql", "SELECT 1")),
        (f"{PROJECT}/replay/0190-s1?t=30", ("replay", "0190-s1")),
        (f"{PROJECT}/replay/home?sessionRecordingId=0190-s1", ("replay", "0190-s1")),
        (f"{PROJECT}/feature_flags/42", ("flag", "42")),
        (f"{PROJECT}/persons/a%20b", ("person", "a b")),
        (f"{PROJECT}/feature_flags/my-key", None),
        (f"{PROJECT}/insights/new", None),
        (f"{PROJECT}/insights/new#q=%7B%22kind%22%3A%22TrendsQuery%22%7D", None),
        (f"{PROJECT}/replay/home", None),
        (f"{PROJECT}/sql?open_query=", None),
        (f"{PROJECT}/settings/project", None),
        ("https://us.posthog.com/project/3/insights/9pQx3", None),
        ("https://eu.posthog.com/project/2/insights/9pQx3", None),
        ("https://us.posthog.com.evil.example/project/2/insights/9pQx3", None),
        ("javascript:alert(1)", None),
    ]
)
def test_parse_object_url(url: str, expected: tuple[str, str] | None) -> None:
    match = parse_object_url(url, project_url=PROJECT)
    assert (None if match is None else (match.kind, match.object_id)) == expected
