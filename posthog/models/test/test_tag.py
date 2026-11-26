from posthog.models.tag import tagify_filter


def test_tagify_filter_normalizes_names() -> None:
    assert tagify_filter(["Finance", " FINANCE ", "ops"]) == ["finance", "ops"]


def test_tagify_filter_skips_non_string_and_blank_entries() -> None:
    assert tagify_filter([None, {"a": 1}, ["x"]]) == []
    assert tagify_filter([" ", ""]) == []
