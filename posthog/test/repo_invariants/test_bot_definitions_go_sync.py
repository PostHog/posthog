import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = REPO_ROOT / "livestream" / "bot" / "generate_definitions.py"
DEFINITIONS_PATH = REPO_ROOT / "livestream" / "bot" / "definitions.json"


def _load_generator():
    spec = importlib.util.spec_from_file_location("livestream_bot_generate_definitions", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_go_definitions_match_generated_output():
    generator = _load_generator()
    expected = generator.render()
    actual = DEFINITIONS_PATH.read_text()
    assert actual == expected, (
        "livestream/bot/definitions.json is out of sync with BOT_DEFINITIONS. "
        "Run: python livestream/bot/generate_definitions.py"
    )


@pytest.mark.parametrize(
    "pattern,expected",
    [
        # Plain tokens and escaped literals have a substring form the Go matcher can use.
        ("GPTBot", "GPTBot"),
        (r"desktop\.hog\.dev", "desktop.hog.dev"),
        (r"\) AppleWebKit/537\.36 Chrome/", ") AppleWebKit/537.36 Chrome/"),
        ("bne.es_bot", "bne.es_bot"),  # a bare dot stays a literal dot
        # Regex features have no substring form, so the pattern is dropped rather than mangled.
        (r"Chrome/1\d\d.*Edge/1[2-8]\.", None),  # character classes and a quantifier
        (r"Safari/537\.3$", None),  # an anchor
        (r"^Mozilla/5\.0$", None),  # anchors
        (r"(^\s|\s$)", None),  # a group with alternation
        (r"Claude/.*Electron", None),  # a quantifier
    ],
)
def test_to_substring_keeps_literals_and_drops_regex(pattern: str, expected: str | None):
    assert _load_generator().to_substring(pattern) == expected
