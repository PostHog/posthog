import pytest

from products.ai_observability.backend.logic.message_normalizer.errors import RecipeCompileError
from products.ai_observability.backend.logic.message_normalizer.yaml_loader import load_recipe_yaml


def test_reads_yaml_1_2() -> None:
    assert load_recipe_yaml("on: {flag: yes}\nn: 010\nt: ~\n") == {"on": {"flag": "yes"}, "n": 10, "t": None}


@pytest.mark.parametrize(
    "source, expected",
    [
        ("d: 2026-10-28\n", {"d": "2026-10-28"}),
        ("d: 2024-02-30\n", {"d": "2024-02-30"}),
        ("t: 2026-10-28T10:00:00Z\n", {"t": "2026-10-28T10:00:00Z"}),
        ("2024-01-01: 1\n", {"2024-01-01": 1}),
    ],
)
def test_keeps_timestamps_as_text_like_the_frontend_parser(source: str, expected: object) -> None:
    assert load_recipe_yaml(source) == expected


@pytest.mark.parametrize(
    "source",
    ["a: 1\na: 2\n", "rules: [\n", "n: " + "9" * 5000 + "\n", "? [[a]]\n: 1\n"],
    ids=["duplicate key", "broken syntax", "oversized integer", "unhashable key"],
)
def test_rejects_sources_that_cannot_load(source: str) -> None:
    with pytest.raises(RecipeCompileError):
        load_recipe_yaml(source)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("a: &x {b: 1}\nc:\n  <<: *x\n", {"a": {"b": 1}, "c": {"<<": {"b": 1}}}),
        ("c:\n  <<: {a: 1}\n  b: 2\n", {"c": {"<<": {"a": 1}, "b": 2}}),
    ],
    ids=["alias", "inline mapping"],
)
def test_merge_key_stays_a_plain_key(source: str, expected: object) -> None:
    assert load_recipe_yaml(source) == expected


@pytest.mark.parametrize(
    "source, expected",
    [
        ("n: 1_000", {"n": "1_000"}),
        ("n: 1_0.5", {"n": "1_0.5"}),
        ("n: 0b11", {"n": "0b11"}),
        ("n: -0x1", {"n": "-0x1"}),
        ("n: +0o7", {"n": "+0o7"}),
        ("n: 0x_1", {"n": "0x_1"}),
        ("n: 0o17\nm: 0x1F\nk: +12\nj: -3", {"n": 15, "m": 31, "k": 12, "j": -3}),
    ],
)
def test_resolves_only_yaml_1_2_core_numbers(source: str, expected: object) -> None:
    assert load_recipe_yaml(source) == expected
