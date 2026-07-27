#!/usr/bin/env python3
"""
Reverse seed — pull live bundle changes from local PostHog back to disk.

The inverse of `seed.py`. After editing an example agent on the platform —
e.g. iterating on it through the Agent Builder — run this to pull the live
revision's bundle (system prompt, skills, spec) back into the on-disk bundle
so the changes can be reviewed + committed.

For each selected bundle it:
  - finds the application by slug (skips bundles with no application yet),
  - reads the live revision's typed bundle (`GET .../bundle`) for file bodies,
  - writes `agent.md`, each `skills/<id>/SKILL.md`, and any custom
    `tools/<id>/source.ts` into the bundle dir.

Content vs spec:
  - `agent.md` + skill bodies (and custom-tool sources) are written verbatim —
    a lossless round-trip, and the common case (Agent Builder edits to the prompt
    and skills). This is what runs by default.
  - `spec.json` is pulled only with `--spec`. The platform stores the FROZEN
    spec — schema defaults filled in and skill descriptions re-derived from
    each SKILL.md frontmatter at freeze — so pulling it rewrites the file into
    that normalised shape (useful when the Agent Builder changed triggers / tools /
    limits, noisy otherwise). Local-only keys `seed.py` strips on upload (e.g.
    `resume`) are preserved from disk. Review the diff.

Idempotent: a file whose on-disk content already matches is left untouched;
the run prints exactly what changed. Pulls the LIVE revision by default; pass
`--latest` to pull the newest revision regardless of state (e.g. an
un-promoted Agent Builder draft).

Usage:
    # Pull every bundle that has an application on the platform:
    python services/agent-tests/src/examples/pull.py

    # One bundle (selector matches slug exactly or as a substring):
    python services/agent-tests/src/examples/pull.py wake-me-up

    # Comma-separated, or show what would change without writing:
    python services/agent-tests/src/examples/pull.py --only agent-builder,wake-me-up
    DRY_RUN=1 python services/agent-tests/src/examples/pull.py wake-me-up

    # Also pull spec.json (triggers / tools / limits), not just content:
    python services/agent-tests/src/examples/pull.py --spec wake-me-up

    # Pull the newest revision even if it isn't promoted to live:
    python services/agent-tests/src/examples/pull.py --latest wake-me-up

    # Also delete on-disk skills/tools that no longer exist on the platform:
    python services/agent-tests/src/examples/pull.py --prune wake-me-up

Env vars: the same as `seed.py` — PAT (optional in a flox dev env; otherwise
auto-minted via `manage.py setup_local_api_key`), POSTHOG_API, PROJECT_ID,
DRY_RUN. Do NOT set AUTH_MODE / MCP_URL when pulling — they'd make the spec
look perpetually drifted.

Exit codes:
    0  every selected bundle pulled / no-op
    1  one or more bundles failed
    2  bad env / missing PAT / unknown selector
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import seed

EXAMPLES_ROOT = seed.EXAMPLES_ROOT
DRY_RUN = seed.DRY_RUN

# Top-level spec keys `seed.py` strips before upload, so the platform never
# stores them. Preserved from the on-disk `spec.json` when rewriting it.
LOCAL_ONLY_SPEC_KEYS = ("resume",)


class PullError(Exception):
    """A per-bundle failure. Caught by the run loop so one bad bundle doesn't
    abort the others; the run still exits non-zero at the end."""


def log(slug: str, msg: str) -> None:
    prefix = "[DRY] " if DRY_RUN else "[pull] "
    print(f"{prefix}{slug}: {msg}", flush=True)  # noqa: T201 — CLI script


# ---------------------------------------------------------------------------
# Platform reads
# ---------------------------------------------------------------------------


def find_application(slug: str) -> str | None:
    """The application id for `slug`, or None if it doesn't exist yet."""
    status, payload = seed._req("GET", "/agent_applications/")
    if status != 200:
        raise PullError(f"failed to list applications: {status} {payload}")
    for app in payload.get("results", []):
        if app.get("slug") == slug:
            return app["id"]
    return None


def pick_revision(app_id: str, latest: bool) -> str | None:
    """The revision to pull: the live one by default, or the newest revision
    (any state) when `latest` is set. None if there's nothing to pull."""
    status, app = seed._req("GET", f"/agent_applications/{app_id}/")
    if status != 200:
        raise PullError(f"failed to read application: {status} {app}")
    if not latest:
        return app.get("live_revision")
    status, payload = seed._req("GET", f"/agent_applications/{app_id}/revisions/")
    if status != 200:
        raise PullError(f"failed to list revisions: {status} {payload}")
    revs = payload.get("results", [])
    if not revs:
        return app.get("live_revision")
    newest = max(revs, key=lambda r: r.get("created_at", ""))
    return newest.get("id")


def get_typed_bundle(app_id: str, rev_id: str) -> dict:
    """`{ agent_md, skills:[{id,description,body}], tools:[{id,source,...}], spec }`."""
    status, payload = seed._req("GET", f"/agent_applications/{app_id}/revisions/{rev_id}/bundle/")
    if status != 200:
        raise PullError(f"failed to read bundle for {rev_id}: {status} {payload}")
    bundle = payload.get("bundle")
    if not isinstance(bundle, dict):
        raise PullError(f"bundle read returned no bundle for {rev_id}: {payload}")
    return bundle


def get_full_spec(app_id: str, rev_id: str) -> dict:
    """The full frozen spec (includes derived `skills[]` + `tools[]`)."""
    status, rev = seed._req("GET", f"/agent_applications/{app_id}/revisions/{rev_id}/")
    if status != 200:
        raise PullError(f"failed to read revision {rev_id}: {status} {rev}")
    spec = rev.get("spec")
    if not isinstance(spec, dict):
        raise PullError(f"revision {rev_id} has no spec")
    return spec


# ---------------------------------------------------------------------------
# Disk writes
# ---------------------------------------------------------------------------


def write_if_changed(bundle_root: Path, rel_path: str, content: str) -> bool:
    """Write `content` to `rel_path` under the bundle only if it differs. Logs
    one of `+ added` / `~ updated` / (silent when unchanged). Honors DRY_RUN."""
    dest = bundle_root / rel_path
    existed = dest.is_file()
    if existed and dest.read_text() == content:
        return False
    verb = "~ updated" if existed else "+ added"
    log(bundle_root.name, f"{verb} {rel_path}")
    if not DRY_RUN:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
    return True


def serialize_spec(spec: dict) -> str:
    """Match the on-disk bundle convention: 4-space indent, trailing newline,
    non-ASCII left intact (prompts use em-dashes etc.)."""
    return json.dumps(spec, indent=4, ensure_ascii=False) + "\n"


def reconstruct_spec(platform_spec: dict, on_disk_spec: dict) -> dict:
    """The spec to write to disk: the platform's spec (it owns model / triggers
    / tools / skills / mcps / …) plus any local-only keys (`resume`) carried
    over from the existing file, ordered to match the on-disk file so the diff
    stays minimal."""
    merged = dict(platform_spec)
    for key in LOCAL_ONLY_SPEC_KEYS:
        if key in on_disk_spec and key not in merged:
            merged[key] = on_disk_spec[key]
    ordered: dict = {}
    for key in on_disk_spec:
        if key in merged:
            ordered[key] = merged[key]
    for key in merged:
        if key not in ordered:
            ordered[key] = merged[key]
    return ordered


# ---------------------------------------------------------------------------
# Per-bundle pull
# ---------------------------------------------------------------------------


def pull_bundle(bundle_root: Path, latest: bool, prune: bool, pull_spec: bool) -> None:
    slug = bundle_root.name
    app_id = find_application(slug)
    if not app_id:
        log(slug, "no application on the platform — nothing to pull")
        return
    rev_id = pick_revision(app_id, latest)
    if not rev_id:
        log(slug, "no revision to pull (not promoted yet? try --latest)")
        return

    bundle = get_typed_bundle(app_id, rev_id)
    log(slug, f"pulling revision {rev_id}")

    changed = 0

    # agent.md — the system prompt.
    if write_if_changed(bundle_root, "agent.md", bundle.get("agent_md", "")):
        changed += 1

    # Skills — one folder per skill at the platform-canonical path. Bodies
    # round-trip exactly; this is the common case (Agent Builder prose edits).
    pulled_skill_paths: set[str] = set()
    for s in bundle.get("skills", []):
        sid = s.get("id")
        if not sid:
            continue
        rel = f"skills/{sid}/SKILL.md"
        pulled_skill_paths.add(rel)
        if write_if_changed(bundle_root, rel, s.get("body", "")):
            changed += 1

    # Custom tool sources (seed.py doesn't push these, but the Agent Builder may
    # have added one on the platform).
    pulled_tool_dirs: set[str] = set()
    for t in bundle.get("tools", []):
        tid = t.get("id")
        source = t.get("source")
        if not tid or source is None:
            continue
        pulled_tool_dirs.add(f"tools/{tid}")
        if write_if_changed(bundle_root, f"tools/{tid}/source.ts", source):
            changed += 1

    # spec.json — opt-in. The platform stores the FROZEN spec: schema defaults
    # filled in and skill descriptions re-derived from each SKILL.md frontmatter
    # at freeze. That normalisation can't be cleanly un-applied, so pulling it
    # rewrites spec.json into the normalised shape — handy when the Agent Builder
    # changed triggers/tools/limits, noisy otherwise. Off by default; review the
    # diff. Local-only keys seed.py strips (e.g. `resume`) are preserved.
    if pull_spec:
        on_disk_spec = (
            json.loads((bundle_root / "spec.json").read_text()) if (bundle_root / "spec.json").is_file() else {}
        )
        full_spec = get_full_spec(app_id, rev_id)
        if write_if_changed(bundle_root, "spec.json", serialize_spec(reconstruct_spec(full_spec, on_disk_spec))):
            changed += 1
    else:
        log(slug, "spec.json not pulled (pass --spec to also pull spec/trigger/tool changes)")

    prune_orphans(bundle_root, pulled_skill_paths, pulled_tool_dirs, prune)

    if changed == 0:
        log(slug, "content up to date — nothing changed")


def prune_orphans(bundle_root: Path, pulled_skills: set[str], pulled_tools: set[str], prune: bool) -> None:
    """On-disk skills/tools the platform no longer has. With `--prune`, delete
    them; otherwise warn so a stale local file doesn't silently re-seed."""
    slug = bundle_root.name
    skills_dir = bundle_root / "skills"
    if skills_dir.is_dir():
        for f in sorted(skills_dir.rglob("SKILL.md")):
            rel = f.relative_to(bundle_root).as_posix()
            if rel in pulled_skills:
                continue
            _handle_orphan(slug, bundle_root, f.parent if f.parent != skills_dir else f, prune, rel)
    tools_dir = bundle_root / "tools"
    if tools_dir.is_dir():
        for d in sorted(p for p in tools_dir.iterdir() if p.is_dir()):
            rel = d.relative_to(bundle_root).as_posix()
            if rel in pulled_tools:
                continue
            _handle_orphan(slug, bundle_root, d, prune, rel)


def _handle_orphan(slug: str, bundle_root: Path, target: Path, prune: bool, rel: str) -> None:
    if not prune:
        log(slug, f"! on disk but not on platform: {rel} (pass --prune to remove)")
        return
    log(slug, f"- removed {rel}")
    if DRY_RUN:
        return
    if target.is_dir():
        for child in sorted(target.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        target.rmdir()
    elif target.is_file():
        target.unlink()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> tuple[bool, bool, bool, bool, list[str]]:
    """Returns (list_only, latest, prune, pull_spec, selectors)."""
    list_only = latest = prune = pull_spec = False
    selectors: list[str] = []
    for arg in argv:
        if arg == "--list":
            list_only = True
        elif arg == "--latest":
            latest = True
        elif arg == "--prune":
            prune = True
        elif arg == "--spec":
            pull_spec = True
        elif arg.startswith("--only="):
            selectors.extend(s for s in arg.split("=", 1)[1].split(",") if s)
        elif arg == "--only":
            seed.die("--only needs a value, e.g. --only=wake-me-up")
        elif arg.startswith("--"):
            seed.die(f"unknown flag {arg!r}")
        else:
            selectors.append(arg)
    return list_only, latest, prune, pull_spec, selectors


def main() -> None:
    list_only, latest, prune, pull_spec, selectors = parse_args(sys.argv[1:])
    bundles = seed.discover_bundles()
    if not bundles:
        seed.die(f"no bundles found under {EXAMPLES_ROOT}")

    selected = seed.select_bundles(bundles, selectors)

    if list_only:
        print(f"Discovered {len(bundles)} bundle(s) under {EXAMPLES_ROOT}:")  # noqa: T201
        for b in bundles:
            mark = "*" if b in selected else " "
            print(f"  [{mark}] {b.name}")  # noqa: T201
        return

    if not seed.PAT:
        print("[pull] no PAT set — minting the local dev key via setup_local_api_key…")  # noqa: T201
        seed.PAT = seed.mint_dev_pat()
    if not seed.PAT:
        print(  # noqa: T201
            "[pull] FATAL: no PAT. Set PAT=phx_… or run in a flox env where "
            "`manage.py setup_local_api_key` can mint the local dev key.",
            file=sys.stderr,
        )
        sys.exit(2)

    print(  # noqa: T201
        f"[pull] source: {seed.API} project={seed.PROJECT_ID} — "
        f"{len(selected)}/{len(bundles)} bundle(s): {', '.join(b.name for b in selected)}"
    )
    failures: list[tuple[str, str]] = []
    for bundle_root in selected:
        try:
            pull_bundle(bundle_root, latest=latest, prune=prune, pull_spec=pull_spec)
        except PullError as e:
            log(bundle_root.name, f"FAILED — {e}")
            failures.append((bundle_root.name, str(e)))

    ok = len(selected) - len(failures)
    print(f"[pull] done: {ok}/{len(selected)} bundle(s) ok")  # noqa: T201
    if failures:
        print("[pull] failed bundles:", file=sys.stderr)  # noqa: T201
        for slug, msg in failures:
            print(f"  - {slug}: {msg.splitlines()[0]}", file=sys.stderr)  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
