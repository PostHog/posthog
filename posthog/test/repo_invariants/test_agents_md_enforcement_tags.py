import re
from pathlib import Path

MARKER = re.compile(r"\[lint:([^\]]+)\]")
SEMGREP_ID = re.compile(r"^\s*-?\s*id:\s*(\S+)", re.MULTILINE)
RUFF_CODE = re.compile(r"^ruff ([A-Z]+[0-9]+)$")
LEGEND_PLACEHOLDER = "<id>"

# Tags naming a command or CI job rather than a rule id. Add to this set only
# when no single rule id covers the check.
FREE_FORM = {
    "hogli product:lint --all",
    "product:lint",
    "build:openapi CI gate",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _tags(agents_md: str) -> list[str]:
    tags = (tag.strip() for marker in MARKER.findall(agents_md) for tag in marker.split(","))
    return [tag for tag in tags if tag != LEGEND_PLACEHOLDER]


def _semgrep_ids(repo_root: Path) -> set[str]:
    ids: set[str] = set()
    for path in (repo_root / ".semgrep").rglob("*.y*ml"):
        ids.update(SEMGREP_ID.findall(path.read_text(errors="ignore")))
    return ids


def _ruff_selected(repo_root: Path, code: str) -> bool:
    config = (repo_root / "pyproject.toml").read_text(errors="ignore")
    return f'"{code}"' in config


def _resolves(tag: str, repo_root: Path, semgrep_ids: set[str]) -> bool:
    if tag in FREE_FORM:
        return True
    ruff = RUFF_CODE.match(tag)
    if ruff:
        return _ruff_selected(repo_root, ruff.group(1))
    if tag.endswith(".py") or tag.endswith(".txt"):
        return any(repo_root.rglob(tag))
    return tag in semgrep_ids


def test_agents_md_lint_tags_name_something_real():
    # A stale tag is worse than no tag: a reviewer trusts it and skips the check.
    repo_root = _repo_root()
    agents_md = (repo_root / "AGENTS.md").read_text()
    semgrep_ids = _semgrep_ids(repo_root)

    tags = _tags(agents_md)
    assert tags, "AGENTS.md has no [lint: ...] tags — did the marker format change?"

    unresolved = [tag for tag in tags if not _resolves(tag, repo_root, semgrep_ids)]

    assert not unresolved, (
        f"AGENTS.md tags these as machine-enforced, but nothing by that name exists: {unresolved}. "
        "Either the rule was renamed or deleted (fix the tag, or retag the rule as [review]), "
        f"or the tag names a command rather than a rule id (add it to FREE_FORM in {Path(__file__).name})."
    )
