import pytest

from products.ai_observability.backend.logic.message_normalizer.errors import RecipeCompileError
from products.ai_observability.backend.logic.message_normalizer.yaml_loader import MAX_FLOW_DEPTH, load_recipe_yaml


def test_reads_yaml_1_2() -> None:
    assert load_recipe_yaml("on: {flag: yes}\nn: 010\nt: ~\nsep: =\n") == {
        "on": {"flag": "yes"},
        "n": 10,
        "t": None,
        "sep": "=",
    }


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
    [
        "a: 1\na: 2\n",
        "rules: [\n",
        "n: " + "9" * 5000 + "\n",
        "n: 0x" + "f" * 4000 + "\n",
        "? [[a]]\n: 1\n",
        "1: a\n1.0: b\n",
        "%YAML 1.0\n---\nrules: []\n",
        "%YAML 1.3\n---\nrules: []\n",
        "a: !!bool invalid\n",
        'a: !!float ""\n',
        "a: " + "[" * (MAX_FLOW_DEPTH + 1) + "]" * (MAX_FLOW_DEPTH + 1) + "\n",
        "%TAG !e! tag:yaml.org,2002:\n---\na: !e!str b\n",
    ],
    ids=[
        "duplicate key",
        "broken syntax",
        "oversized integer",
        "oversized hex integer",
        "unhashable key",
        "equal numeric keys",
        "YAML 1.0 directive",
        "YAML 1.3 directive",
        "malformed bool tag",
        "malformed float tag",
        "flow nesting past the cap",
        "TAG directive",
    ],
)
def test_rejects_sources_that_cannot_load(source: str) -> None:
    with pytest.raises(RecipeCompileError):
        load_recipe_yaml(source)


@pytest.mark.parametrize(
    "source, expected",
    [
        ("true: a\n1: b\n", {"true": "a", "1": "b"}),
        ("false: a\n0: b\n", {"false": "a", "0": "b"}),
        ('"1": a\n1: b\n', {"1": "b"}),
    ],
    ids=["true and 1", "false and 0", "same field text"],
)
def test_names_fields_by_key_text_like_the_frontend_parser(source: str, expected: object) -> None:
    assert load_recipe_yaml(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "a: &x 1\n",
        "a: &x 1\nb: *x\n",
        "a: &x {b: 1}\nc:\n  <<: *x\n",
        "a0: &a0 [x, x]\n" + "".join(f"a{i}: &a{i} [*a{i - 1}, *a{i - 1}]\n" for i in range(1, 30)),
    ],
    ids=["anchor", "alias", "merge key alias", "doubling aliases"],
)
def test_rejects_anchors_and_aliases(source: str) -> None:
    with pytest.raises(RecipeCompileError, match="anchors .* or aliases"):
        load_recipe_yaml(source)


def test_merge_key_stays_a_plain_key() -> None:
    assert load_recipe_yaml("c:\n  <<: {a: 1}\n  b: 2\n") == {"c": {"<<": {"a": 1}, "b": 2}}


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
