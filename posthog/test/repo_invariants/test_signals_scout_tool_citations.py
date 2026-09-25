"""Guard for MCP tool names cited by the canonical signals scout skills.

A scout body ships to every project and names the MCP tools its run should call. Nothing
resolved those names before this guard, so a renamed or retired tool left a citation that
only surfaced as a failed call at run time, on every run of that scout.

No single rule recognizes a tool name, so the guard reads a citation three ways.

Position is the strongest: a bare kebab token alone on its own line is an invocation, the
shape a fenced example uses. Whatever its name, it must resolve.

Shape covers prose: a backticked kebab token whose last segment is one of the action verbs
the tool naming convention uses. That separates a tool name from the other kebab tokens a
body backticks — skill names, scratchpad key prefixes, frontmatter keys, event and property
names — so a false positive cannot block an unrelated pull request.

The baseline covers the rest: tools whose names carry no action verb, such as `execute-sql`
and `scout-emit-report`. Neither position nor shape sees them in prose, and they are the
most cited tools in the fleet. The baseline pins the ones the corpus relies on today, so
renaming one fails here instead of at run time.

Residual gap: a backticked prose citation that is new, carries no action verb, and names no
tool the catalog ever had. Matching every kebab token instead would flag 103 non-tool tokens
in this corpus, and a false positive here blocks unrelated pull requests.

Regenerate the baseline (after confirming a rename, or when a body cites a new tool):

    DEBUG=1 DJANGO_SETTINGS_MODULE=posthog.settings PYTHONPATH=. python posthog/test/repo_invariants/test_signals_scout_tool_citations.py
"""

import re
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[3]
BASELINE_PATH = Path(__file__).parent / "signals_scout_tool_citations_baseline.txt"
CATALOG_PATH = REPO_ROOT / "services" / "mcp" / "schema" / "tool-definitions-all.json"

TOOL_NAME_VERBS = frozenset(
    {
        "all",
        "cancel",
        "count",
        "create",
        "delete",
        "destroy",
        "forget",
        "get",
        "list",
        "remember",
        "retrieve",
        "search",
        "sync",
        "update",
    }
)
# The token ends at the closing backtick, at whitespace, or at an opening parenthesis, so a
# citation that carries arguments in the same code span — `some-tool {"a": 1}`, `some-tool(a)`
# — still yields the tool name.
CITATION_RE = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)(?=[`\s(])")
# A token alone on its own line, with or without an argument list, which is how a fenced
# example names the tool it calls.
INVOCATION_RE = re.compile(r"^[ \t]*([a-z][a-z0-9]*(?:-[a-z0-9]+)+)(?:\(.*\))?[ \t]*$", re.MULTILINE)


def has_tool_shape(name: str) -> bool:
    return name.rsplit("-", 1)[-1] in TOOL_NAME_VERBS


def catalog_names() -> set[str]:
    return set(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))


def _canonical_sources() -> list[tuple[str, str]]:
    from products.signals.backend.scout_harness.lazy_seed import discover_canonical_skills

    sources: list[tuple[str, str]] = []
    for skill in discover_canonical_skills():
        sources.append((skill.name, skill.body))
        sources.extend((f"{skill.name}/{file.path}", file.content) for file in skill.files)
    return sources


def cited_names() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Kebab tokens in the canonical corpus: the backticked ones, and the invocations."""
    backticked: dict[str, set[str]] = {}
    invoked: dict[str, set[str]] = {}
    for source, text in _canonical_sources():
        for match in CITATION_RE.finditer(text):
            backticked.setdefault(match.group(1), set()).add(source)
        for match in INVOCATION_RE.finditer(text):
            invoked.setdefault(match.group(1), set()).add(source)
    return backticked, invoked


def collect_baseline_names(backticked: dict[str, set[str]], catalog: set[str]) -> set[str]:
    return {name for name in backticked if name in catalog and not has_tool_shape(name)}


def read_baseline() -> set[str]:
    return {line.strip() for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()}


def write_baseline(names: set[str]) -> None:
    BASELINE_PATH.write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("call `some-tool` next", {"some-tool"}),
        ('call `some-tool {"a": 1}` next', {"some-tool"}),
        ("call `some-tool(a)` next", {"some-tool"}),
        ("call `some-tool` and `other-tool`", {"some-tool", "other-tool"}),
        ("no_kebab_here and `single`", set()),
    ],
)
def test_citation_pattern_reads_each_backticked_form(text: str, expected: set[str]) -> None:
    assert {match.group(1) for match in CITATION_RE.finditer(text)} == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("```json\nsome-tool\n{}\n```", {"some-tool"}),
        ("```\n  some-tool(a, b)\n```", {"some-tool"}),
        ("a line with some-tool in prose", set()),
    ],
)
def test_invocation_pattern_reads_a_tool_named_on_its_own_line(text: str, expected: set[str]) -> None:
    assert {match.group(1) for match in INVOCATION_RE.finditer(text)} == expected


def test_tool_shaped_citations_resolve_against_the_catalog() -> None:
    catalog = catalog_names()
    assert catalog, f"empty MCP tool catalog at {CATALOG_PATH}"
    backticked, invoked = cited_names()
    unresolvable: dict[str, set[str]] = {
        name: sources for name, sources in backticked.items() if has_tool_shape(name) and name not in catalog
    }
    for name, sources in invoked.items():
        if name not in catalog:
            unresolvable.setdefault(name, set()).update(sources)
    assert not unresolvable, (
        "Canonical scout skills cite tool names the MCP catalog does not resolve. A scout "
        "that calls one fails on every run. Point each citation at a live tool:\n"
        + "\n".join(f"  {name} ({', '.join(sorted(sources))})" for name, sources in sorted(unresolvable.items()))
    )


def test_baseline_tool_citations_still_resolve() -> None:
    catalog = catalog_names()
    baseline = read_baseline()
    current = collect_baseline_names(cited_names()[0], catalog)
    missing = sorted(baseline - current)
    added = sorted(current - baseline)
    assert not missing, (
        "Tool names the canonical scouts rely on no longer resolve against the MCP catalog. "
        "Repoint each citation at the live tool, then regenerate:\n  DEBUG=1 DJANGO_SETTINGS_MODULE=posthog.settings PYTHONPATH=. python posthog/test/repo_invariants/test_signals_scout_tool_citations.py\n"
        + "\n".join(f"  {name}" for name in missing)
    )
    assert not added, (
        "Canonical scouts cite tools the baseline does not pin. Confirm each name is a real "
        "tool, then regenerate:\n  DEBUG=1 DJANGO_SETTINGS_MODULE=posthog.settings PYTHONPATH=. python posthog/test/repo_invariants/test_signals_scout_tool_citations.py\n"
        + "\n".join(f"  {name}" for name in added)
    )


if __name__ == "__main__":
    import django

    django.setup()
    collected = collect_baseline_names(cited_names()[0], catalog_names())
    write_baseline(collected)
    print(f"baseline written: {len(collected)} pinned tool names")  # noqa: T201
