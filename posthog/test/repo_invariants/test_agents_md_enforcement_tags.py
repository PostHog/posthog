import re
import tomllib
from pathlib import Path

MARKER = re.compile(r"\[lint:([^\]]+)\]")
SEMGREP_ID = re.compile(r"^\s*-?\s*id:\s*(\S+)", re.MULTILINE)
RUFF_CODE = re.compile(r"^ruff ([A-Z]+[0-9]*)$")
WELL_FORMED = re.compile(r"`\[lint:[^\]]+\]`|`\[review\]`")
LEGEND_PLACEHOLDER = "<id>"

# A file tag must name something CI executes. A data file the check reads is not
# the check: delete the step that reads it and the file still sits there.
EXECUTED_CHECK_ROOTS = ("posthog/test/repo_invariants", ".github/scripts")

# The rule trees ci-security.yaml loads. A rule parked anywhere else in .semgrep
# is not loaded by a blocking job, so it cannot back a tag.
LOADED_SEMGREP_ROOTS = (".semgrep/rules/security", ".semgrep/rules/devex")

# Agent guides whose every rule must declare what enforces it.
TAGGED_GUIDES = (".agents/architecture.md", ".agents/code-style.md")

# Every agent guide that may carry a [lint: ...] tag.
GUIDES_WITH_TAGS = ("AGENTS.md", ".agents/ci.md", *TAGGED_GUIDES)

# Tags naming a command or CI job rather than a rule id. Add to this set only
# when no single rule id covers the check.
FREE_FORM = {
    "hogli product:lint --all",
    "product:lint",
    "build:openapi CI gate",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _read(repo_root: Path, guides: tuple[str, ...]) -> str:
    return "\n".join((repo_root / guide).read_text() for guide in guides)


def _tags(guides: str) -> list[str]:
    tags = (tag.strip() for marker in MARKER.findall(guides) for tag in marker.split(","))
    return [tag for tag in tags if tag != LEGEND_PLACEHOLDER]


def _rules(guides: str) -> list[str]:
    return [line for line in guides.split("\n") if line.startswith("- ")]


def _semgrep_ids(repo_root: Path) -> set[str]:
    ids: set[str] = set()
    for root in LOADED_SEMGREP_ROOTS:
        for path in (repo_root / root).rglob("*.y*ml"):
            ids.update(SEMGREP_ID.findall(path.read_text(errors="ignore")))
    return ids


def _ruff_enforces(repo_root: Path, code: str) -> bool:
    lint = tomllib.loads((repo_root / "pyproject.toml").read_text())["tool"]["ruff"].get("lint", {})
    # Ruff selectors are prefixes and the longest match wins, so a category-level
    # ignore switches off every code under it unless a longer select overrides.
    ignored = max((e for e in lint.get("ignore", []) if code.startswith(e)), key=len, default="")
    selected = lint.get("select", []) + lint.get("extend-select", [])
    chosen = max((e for e in selected if code.startswith(e)), key=len, default="")
    if ignored and len(ignored) >= len(chosen):
        return False
    # A code exempted for whole trees does not hold repo-wide, so a bare tag would
    # tell a reviewer CI covers paths where it accepts the violation.
    for config, table in ((lint, "per-file-ignores"), (_products_ruff(repo_root), "per-file-ignores")):
        if any(code in codes for codes in config.get(table, {}).values()):
            return False
    return bool(chosen)


def _products_ruff(repo_root: Path) -> dict:
    path = repo_root / "products" / "ruff.toml"
    if not path.exists():
        return {}
    config = tomllib.loads(path.read_text())
    return config.get("lint", config)


def _resolves(tag: str, repo_root: Path, semgrep_ids: set[str]) -> bool:
    if tag in FREE_FORM:
        return True
    ruff = RUFF_CODE.match(tag)
    if ruff:
        return _ruff_enforces(repo_root, ruff.group(1))
    if tag.endswith(".py"):
        return any(path.is_file() for root in EXECUTED_CHECK_ROOTS for path in (repo_root / root).rglob(tag))
    return tag in semgrep_ids


def test_agents_md_lint_tags_name_something_real() -> None:
    # A stale tag is worse than no tag: a reviewer trusts it and skips the check.
    repo_root = _repo_root()
    semgrep_ids = _semgrep_ids(repo_root)

    tags = _tags(_read(repo_root, GUIDES_WITH_TAGS))
    assert tags, "The agent guides have no [lint: ...] tags — did the marker format change?"

    unresolved = [tag for tag in tags if not _resolves(tag, repo_root, semgrep_ids)]

    assert not unresolved, (
        f"The agent guides tag these as machine-enforced, but nothing by that name enforces them: {unresolved}. "
        "Either the rule was renamed or deleted, or a ruff code moved to `ignore` or a per-file exemption "
        "list (fix the tag, or retag the "
        f"rule as [review]), or the tag names a command rather than a rule id (add it to FREE_FORM in {Path(__file__).name})."
    )


def test_every_architecture_and_code_style_rule_is_tagged() -> None:
    # An untagged rule reads as review-only without saying so, which is the ambiguity the tags remove.
    rules = _rules(_read(_repo_root(), TAGGED_GUIDES))
    assert rules, "Found no rules to check — did the guides move?"

    untagged = [rule[:80] for rule in rules if not WELL_FORMED.search(rule)]

    assert not untagged, (
        f"These architecture and code style rules carry no well-formed enforcement tag: {untagged}. "
        "Add `[lint: <rule-id>]` when a linter or invariant test blocks the violation, or `[review]` when "
        "nothing catches it. An empty or unclosed marker does not count."
    )
