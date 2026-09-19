"""Guard for MCP tool names cited by the canonical signals scout skills.

A scout body ships to every project and names the MCP tools its run should call. Nothing
resolved those names before this guard, so a renamed or retired tool left a citation that
only surfaced as a failed call at run time, on every run of that scout.

The guard has two halves, because one rule cannot recognize a tool name on its own.

Shape covers the common case: a backticked lowercase-kebab token whose last segment is one
of the action verbs the tool naming convention uses. That separates a tool name from the
other kebab tokens a body backticks — skill names, scratchpad key prefixes, frontmatter
keys, event and property names — so a false positive cannot block an unrelated pull request.

The baseline covers the rest: tools whose names carry no action verb, such as `execute-sql`
and `scout-emit-report`. Shape cannot see them, and they are the most cited tools in the
fleet. The baseline pins the ones the corpus relies on today, so renaming one fails here
instead of at run time.

Residual gap: a body that introduces a NEW non-verb name which no tool ever had is caught
only as a baseline addition, and regenerating would drop it. Check an addition before you
regenerate.

Regenerate the baseline (after confirming a rename, or when a body cites a new tool):

    DEBUG=1 DJANGO_SETTINGS_MODULE=posthog.settings PYTHONPATH=. python posthog/test/repo_invariants/test_signals_scout_tool_citations.py
"""

import re
import json
from pathlib import Path

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
# The token ends at the closing backtick or at whitespace, so a citation that carries inline
# arguments in the same code span — `some-tool {"a": 1}` — still yields the tool name.
CITATION_RE = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)(?=[`\s])")


def has_tool_shape(name: str) -> bool:
    return name.rsplit("-", 1)[-1] in TOOL_NAME_VERBS


def catalog_names() -> set[str]:
    return set(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))


def cited_names() -> dict[str, set[str]]:
    """Every backticked kebab token in the canonical corpus, mapped to where it appears."""
    from products.signals.backend.scout_harness.lazy_seed import discover_canonical_skills

    citations: dict[str, set[str]] = {}
    for skill in discover_canonical_skills():
        sources = [(skill.name, skill.body)] + [(f"{skill.name}/{f.path}", f.content) for f in skill.files]
        for source, text in sources:
            for match in CITATION_RE.finditer(text):
                citations.setdefault(match.group(1), set()).add(source)
    return citations


def collect_baseline_names(citations: dict[str, set[str]], catalog: set[str]) -> set[str]:
    return {name for name in citations if name in catalog and not has_tool_shape(name)}


def read_baseline() -> set[str]:
    return {line.strip() for line in BASELINE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()}


def write_baseline(names: set[str]) -> None:
    BASELINE_PATH.write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")


def test_tool_shaped_citations_resolve_against_the_catalog() -> None:
    catalog = catalog_names()
    assert catalog, f"empty MCP tool catalog at {CATALOG_PATH}"
    unresolvable = {
        name: sources for name, sources in cited_names().items() if has_tool_shape(name) and name not in catalog
    }
    assert not unresolvable, (
        "Canonical scout skills cite tool names the MCP catalog does not resolve. A scout "
        "that calls one fails on every run. Point each citation at a live tool:\n"
        + "\n".join(f"  {name} ({', '.join(sorted(sources))})" for name, sources in sorted(unresolvable.items()))
    )


def test_baseline_tool_citations_still_resolve() -> None:
    catalog = catalog_names()
    baseline = read_baseline()
    current = collect_baseline_names(cited_names(), catalog)
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
    collected = collect_baseline_names(cited_names(), catalog_names())
    write_baseline(collected)
    print(f"baseline written: {len(collected)} pinned tool names")  # noqa: T201
