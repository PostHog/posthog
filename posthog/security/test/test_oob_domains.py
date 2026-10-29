import json
from pathlib import Path

import pytest

from posthog.security.oob_domains import matched_oob_domain, oob_domains


@pytest.mark.parametrize(
    "host",
    ["oast.live", "x.oast.live", "a.b.oast.pro", "burpcollaborator.net", "sub.oastify.com", "OAST.ME", "oast.me."],
)
def test_matches_listed_domains(host: str) -> None:
    assert matched_oob_domain(host) is not None


@pytest.mark.parametrize(
    "host",
    ["notoast.me", "oast.me.evil.example", "example.com", "", "myoast.live"],
)
def test_passes_other_hosts(host: str) -> None:
    assert matched_oob_domain(host) is None


def test_matches_the_idna_form_of_a_listed_domain() -> None:
    assert matched_oob_domain("ｏａｓｔ.ｍｅ") == "oast.me"


def test_returns_the_matched_domain() -> None:
    assert matched_oob_domain("abc.oast.live") == "oast.live"


def test_file_and_loader_agree() -> None:
    raw = json.loads((Path(__file__).parents[1] / "crosslang" / "oob_domains.json").read_text())
    assert oob_domains() == frozenset(raw["domains"])


def test_a_broken_file_matches_nothing_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    import posthog.security.oob_domains as module

    module.oob_domains.cache_clear()
    monkeypatch.setattr(module, "_DOMAINS_PATH", Path("/nonexistent/oob_domains.json"))
    try:
        assert matched_oob_domain("oast.live") is None
    finally:
        module.oob_domains.cache_clear()
