#!/usr/bin/env python3
"""Fail when a GitHub Actions cache WRITE could land on a non-default branch ref.

A cache written on a PR/branch ref is scoped to that ref alone: no other branch
can read it, it evicts the shared default-branch cache, and it only ever serves
that one PR's re-runs. Near the 10 GB repo cache cap that churns the useful
master caches out via LRU. This gate fails on any such write.

A cache WRITE is one of:
  - actions/cache@         combined action; auto-saves every run in its post step
  - actions/cache/save@    explicit save
  - actions/setup-*@ with a truthy `cache:` input — auto-saves in a post step that
    can't be gated (gating the whole step would skip the toolchain on PRs)

A write is FINE when any of these hold — no baseline needed:
  1. Its workflow can't run on a branch ref at all (triggers are master-only:
     push to the default branch, schedule, workflow_dispatch, workflow_run).
  2. The step `if:` gates it to the default branch (github.ref == 'refs/heads/master',
     ref_name == 'master', or event_name == 'push').
  3. Its cache key embeds a per-PR/branch/run identifier (e.g.
     github.event.pull_request.number) — i.e. it's *deliberately* unique, not a
     shared cache that got fragmented.

setup-* auto-caches can never be gated, so on a branch-running workflow they
always fail (replace with an explicit restore + gated save — see
.github/actions/pnpm-install/action.yml).

Usage: python .github/scripts/cache_audit.py   # exit 1 on any violation
"""

# ruff: noqa: T201 — this is a CLI gate; printing its findings is the point

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BRANCHES = {"master", "main"}

# setup actions whose `cache:` input enables an ungatable post-save
SETUP_CACHE_ACTIONS = (
    "actions/setup-node",
    "actions/setup-python",
    "actions/setup-go",
    "actions/setup-java",
    "actions/setup-dotnet",
    "actions/setup-ruby",
)

# triggers that can run a workflow on a non-default ref (PR head, feature branch, merge queue)
BRANCH_REF_TRIGGERS = {"pull_request", "pull_request_target", "merge_group", "workflow_call"}

# in a step `if:`, these restrict a write to the default branch
GATE_MARKERS = ("refs/heads/master", "ref_name=='master'", "event_name=='push'")

# in a cache key, these make the entry deliberately unique per ref/PR/run
PER_REF_KEY_MARKERS = (
    "github.event.pull_request.number",
    "github.event.number",
    "github.head_ref",
    "github.ref_name",
    "github.run_id",
)


def iter_yaml_files() -> list[Path]:
    workflows = sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))
    actions = sorted((REPO_ROOT / ".github" / "actions").glob("*/action.y*ml"))
    return workflows + actions


def iter_steps(doc: dict) -> list[dict]:
    """Every step dict in a workflow (jobs.*.steps) or composite action (runs.steps)."""
    steps: list[dict] = []
    for job in (doc.get("jobs") or {}).values():
        if isinstance(job, dict):
            steps.extend(s for s in (job.get("steps") or []) if isinstance(s, dict))
    runs = doc.get("runs")
    if isinstance(runs, dict):
        steps.extend(s for s in (runs.get("steps") or []) if isinstance(s, dict))
    return steps


def push_is_default_only(cfg: object) -> bool:
    # bare `push:` (no filter) runs on every branch push — can leak
    if not isinstance(cfg, dict):
        return False
    branches = cfg.get("branches")
    if branches:
        return all(b in DEFAULT_BRANCHES for b in branches)
    # push restricted to tags only (release pushes) — treat as default-scoped
    return bool(cfg.get("tags"))


def can_run_on_branch_ref(doc: dict) -> bool:
    """True if this file's steps can execute on a non-default ref, so writes must be safe.

    A composite action (no triggers, has `runs`) runs wherever it's called, so it
    always qualifies. Note PyYAML parses a bare `on:` key as the boolean True.
    """
    on = doc.get("on", doc.get(True))
    if on is None:
        return "runs" in doc  # composite action -> assume it can hit a branch ref
    if isinstance(on, str):
        triggers = {on: None}
    elif isinstance(on, list):
        triggers = dict.fromkeys(on)
    elif isinstance(on, dict):
        triggers = on
    else:
        return True
    for name, cfg in triggers.items():
        if name in BRANCH_REF_TRIGGERS:
            return True
        if name == "push" and not push_is_default_only(cfg):
            return True
    return False


def write_kind(step: dict) -> str | None:
    """Classify a step as a cache write, or None if it isn't one."""
    uses = str(step.get("uses") or "")
    if uses.startswith("actions/cache/restore@"):
        return None
    if uses.startswith("actions/cache/save@"):
        return "cache/save"
    if uses.startswith("actions/cache@"):
        return "cache (combined)"
    if uses.startswith(SETUP_CACHE_ACTIONS) and (step.get("with") or {}).get("cache"):
        return "setup auto-cache"
    return None


def is_gated(step: dict) -> bool:
    condition = str(step.get("if") or "").replace(" ", "")
    return any(marker in condition for marker in GATE_MARKERS)


def key_is_per_ref(step: dict) -> bool:
    key = str((step.get("with") or {}).get("key") or "").replace(" ", "")
    return any(marker in key for marker in PER_REF_KEY_MARKERS)


def find_violations() -> list[dict]:
    violations: list[dict] = []
    for path in iter_yaml_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            doc = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            print(f"::warning::cache-audit could not parse {rel}: {exc}")
            continue
        if not isinstance(doc, dict) or not can_run_on_branch_ref(doc):
            continue
        for step in iter_steps(doc):
            kind = write_kind(step)
            if kind is None:
                continue
            if kind != "setup auto-cache" and (is_gated(step) or key_is_per_ref(step)):
                continue
            label = step.get("name") or step.get("uses") or "<unnamed>"
            violations.append({"where": f"{rel} :: {label}", "kind": kind})
    return violations


def main() -> int:
    violations = find_violations()
    if not violations:
        print("cache-audit: OK — every cache write is default-branch-only, gated, or per-ref keyed.")
        return 0

    print("cache-audit: FAIL — cache write(s) that can land on a branch ref:\n")
    for v in sorted(violations, key=lambda v: v["where"]):
        print(f"  [{v['kind']}] {v['where']}")
    print(
        "\nFix one of these ways:"
        "\n  - gate the save to the default branch: `if: github.ref == 'refs/heads/master'`"
        "\n  - replace a setup-* `cache:` input with an explicit restore + gated save"
        "\n    (see .github/actions/pnpm-install/action.yml)"
        "\n  - if the cache is meant to be per-PR, key it on github.event.pull_request.number"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
