import pytest

from products.aeo.backend.facade.contracts import ModifierKind
from products.aeo.backend.keywords import check_modifiers, modifier_kind, tokenize


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Self-Hosted analytics", ["self-hosted", "analytics"]),
        ("site:example.com pricing.", ["site:example.com", "pricing"]),
        ("acme.io, (docs)! 2026?", ["acme.io", "docs", "2026"]),
        ("vs/alternatives -- what's new", ["vs", "alternatives", "what", "s", "new"]),
    ],
)
def test_tokenize_keeps_domains_hyphens_and_site_searches_whole(text: str, expected: list[str]) -> None:
    assert tokenize(text) == expected


@pytest.mark.parametrize(
    "prompt, searches, expected",
    [
        (
            "best analytics tool",
            ["self hosted analytics 2026", "self hosted analytics pricing"],
            {"self", "hosted", "self hosted", "2026", "pricing"},
        ),
        ("analytics for startups", ["example com analytics", "a b of the"], {"example"}),
        ("self-hosted analytics", ["self hosted analytics"], set()),
        ("web analytics", ["site:example.com analytics"], {"site:example.com"}),
    ],
)
def test_check_modifiers_are_new_words_and_phrases_of_new_words(
    prompt: str, searches: list[str], expected: set[str]
) -> None:
    assert set(check_modifiers(prompt, searches)) == expected


@pytest.mark.parametrize(
    "term, expected",
    [
        ("2026", ModifierKind.FRESHNESS),
        ("1989", ModifierKind.OTHER),
        ("latest", ModifierKind.FRESHNESS),
        ("pricing plans", ModifierKind.PRICING),
        ("vs acme", ModifierKind.COMPARISON),
        ("acme", ModifierKind.COMPETITOR),
        ("official docs", ModifierKind.DOCS),
        ("site:acme.io", ModifierKind.SITE),
        ("self hosted", ModifierKind.OTHER),
    ],
)
def test_modifier_kind(term: str, expected: ModifierKind) -> None:
    assert modifier_kind(term, frozenset({"acme"})) == expected
