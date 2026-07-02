from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CI_AGENTS = _REPO_ROOT / ".github" / "workflows" / "ci-agents.yml"
_GENERATED_DIR = Path(__file__).resolve().parent.parent / "logic"


def _glob_match(path: str, pattern: str) -> bool:
    # fnmatch's `*` crosses `/`, but the CI gate (dorny/paths-filter → picomatch) treats `*` as
    # single-segment and `**` as multi-segment. Match the gate so we don't greenlight a pattern it wouldn't.
    p_segs = path.split("/")
    pat_segs = pattern.split("/")

    def match(pi: int, si: int) -> bool:
        if pi == len(pat_segs):
            return si == len(p_segs)
        if pat_segs[pi] == "**":
            return any(match(pi + 1, k) for k in range(si, len(p_segs) + 1))
        if si == len(p_segs):
            return False
        if fnmatch.fnmatch(p_segs[si], pat_segs[pi]):
            return match(pi + 1, si + 1)
        return False

    return match(0, 0)


def _agents_filter_patterns() -> list[str]:
    workflow = yaml.safe_load(_CI_AGENTS.read_text(encoding="utf-8"))
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            with_block: dict[str, Any] = step.get("with") or {}
            raw = with_block.get("filters")
            if not isinstance(raw, str):
                continue
            parsed = yaml.safe_load(raw) or {}
            agents = parsed.get("agents")
            if isinstance(agents, list):
                return [p for p in agents if isinstance(p, str)]
    raise AssertionError("could not find the `agents` path filter in ci-agents.yml")


def test_ci_agents_filter_covers_every_generated_artifact() -> None:
    patterns = _agents_filter_patterns()
    generated = sorted(p.name for p in _GENERATED_DIR.glob("*.generated.json"))
    assert len(generated) >= 4, "generated artifacts missing — did the path change?"

    for name in generated:
        rel = f"products/agent_platform/backend/logic/{name}"
        covered = any(_glob_match(rel, pattern) for pattern in patterns)
        assert covered, (
            f"{rel} is not covered by the ci-agents path filter, so an edit to it "
            f"would not re-run the freshness guard. Add its directory to the `agents` "
            f"filter in .github/workflows/ci-agents.yml."
        )
