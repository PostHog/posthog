from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CI_AGENTS = _REPO_ROOT / ".github" / "workflows" / "ci-agents.yml"
_GENERATED_DIR = Path(__file__).resolve().parent.parent / "logic"


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
    assert generated, "no *.generated.json artifacts found — did the path change?"

    for name in generated:
        rel = f"products/agent_platform/backend/logic/{name}"
        # A `**` glob in the filter also covers this file; fnmatch treats `**`
        # loosely, which is fine — we only need at least one pattern to match.
        covered = any(fnmatch.fnmatch(rel, pattern.replace("**", "*")) for pattern in patterns)
        assert covered, (
            f"{rel} is not covered by the ci-agents path filter, so an edit to it "
            f"would not re-run the freshness guard. Add its directory to the `agents` "
            f"filter in .github/workflows/ci-agents.yml."
        )
