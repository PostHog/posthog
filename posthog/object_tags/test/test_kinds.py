from posthog.object_tags.kinds import OBJECT_KIND_ALIASES, OBJECT_KINDS, object_web_path, resolve_object_kind


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
