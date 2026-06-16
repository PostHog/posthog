#!/usr/bin/env python3
"""
Idempotent seeder for the example agent bundles in this directory.

Discovers every bundle (a subdir holding `spec.json` + `agent.md`) and runs the
deploy pipeline for each selected one against a target PostHog project:

    create application -> create/branch draft revision -> push typed bundle ->
    patch spec -> validate -> freeze -> promote

Idempotent: a bundle whose live revision already matches (per-file sha256 AND
spec) is a no-op; a drifted bundle branches a new draft and re-promotes,
leaving the previously-live revision archived.

Usage:
    # Seed every discovered bundle into the default local project:
    PAT=phx_... python services/agent-tests/src/examples/seed.py

    # Seed a subset — selectors match a bundle slug exactly or as a substring:
    PAT=phx_... python services/agent-tests/src/examples/seed.py concierge approval

    # Same, comma-separated:
    PAT=phx_... python services/agent-tests/src/examples/seed.py --only agent-concierge,agent-approval-demo

    # Show what would be seeded without touching anything:
    python services/agent-tests/src/examples/seed.py --list
    DRY_RUN=1 PAT=phx_... python services/agent-tests/src/examples/seed.py

Args:
    positional   Zero or more bundle selectors. Each matches a bundle whose
                 slug equals the selector or contains it. No selectors -> all.
    --only a,b   Comma-separated selectors (alternative to positional).
    --list       Print discovered bundles and exit (no PAT needed).

Env vars:
    PAT            PostHog personal API key with agents:write scope. Optional in
                   local dev — when unset, the seed mints the deterministic dev
                   key via `manage.py setup_local_api_key` (same as
                   `hogli dev:api-key`). Required when not in a flox env.
    POSTHOG_API    Base API URL (default http://localhost:8010)
    PROJECT_ID     Target project id (default 1)
    DRY_RUN        '1' -> print the plan without mutating
    SEED_DUMMY_SECRETS  '1' -> set obviously-fake placeholders for any required
                   secret not already set, so secret-gated agents (e.g. slack)
                   can promote locally. The agents won't actually function.
    AUTH_MODE      Override every bundle's auth modes (e.g. `public`, `pat`)
    MCP_URL        Rewrite every mcps[].url across all bundles (local-dev)
    MCP_URL_<id>   Rewrite only the mcps entry whose id matches; wins over MCP_URL

Exit codes:
    0  every selected bundle deployed / re-promoted / no-op
    1  one or more bundles failed (validation or platform error)
    2  bad env / missing PAT / unknown selector
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

EXAMPLES_ROOT = Path(__file__).resolve().parent
API = os.environ.get("POSTHOG_API", "http://localhost:8010").rstrip("/")
PROJECT_ID = os.environ.get("PROJECT_ID", "1")
PAT = os.environ.get("PAT")
DRY_RUN = os.environ.get("DRY_RUN") == "1"

# Curated application name + description per slug. Bundles not listed fall back
# to a title-cased slug and a generic description — new examples seed with zero
# config, this dict just preserves nicer copy for the ones we care about.
METADATA: dict[str, dict[str, str]] = {
    "agent-approval-demo": {
        "name": "Approval demo agent",
        "description": "Smallest possible agent that demonstrates approval-gated tool calls — chat with it and ask it to save a note.",
    },
    "agent-concierge": {
        "name": "Agent concierge",
        "description": "Meta-agent for the platform.",
    },
}

# Trigger config fields the Django write-schema accepts today. It intentionally
# lags the zod schema for some fields (e.g. chat/mcp `allow_restart`), so we
# strip anything not listed here before writing. Keep aligned with
# `products/agent_platform/backend/spec_schema.py`, not just `spec.ts`.
ALLOWED_TRIGGER_CONFIG: dict[str, set[str]] = {
    "chat": {"allow_restart"},
    "mcp": {"allow_restart"},
    "webhook": {"path"},
    "slack": {
        "channel_id",
        "mention_only",
        "auto_resume_threads",
        "allow_workspace_participants",
        "ack_reaction",
        "allow_direct_messages",
        "trusted_workspaces",
    },
    "cron": {"name", "schedule", "timezone", "prompt", "external_key", "catch_up", "max_catch_up_age_seconds"},
}

# Triggers that carry their own per-trigger `auth` block. Intrinsic triggers
# (slack / cron) are gated differently (signing secret / internal) and carry no
# auth modes. Mirrors the declarative/intrinsic split in `spec.ts`.
DECLARATIVE_TRIGGERS: set[str] = {"webhook", "chat", "mcp"}

# Secret keys each trigger type requires before promote — mirrors
# TRIGGER_REQUIRED_SECRETS in products/agent_platform/backend/spec_schema.py.
# Used only by the optional SEED_DUMMY_SECRETS placeholder path below.
TRIGGER_REQUIRED_SECRETS: dict[str, list[str]] = {
    "slack": ["SLACK_SIGNING_SECRET", "SLACK_BOT_TOKEN"],
}

# Opt-in: set obviously-fake placeholder values for any secret an agent requires
# (declared `spec.secrets[]` + per-trigger required keys) that isn't already
# set, so secret-gated agents (slack, …) can promote in local dev. The agents
# won't actually function — Slack signature checks etc. will fail — but they go
# live + visible in the console. Never overwrites an existing value.
SEED_DUMMY_SECRETS = os.environ.get("SEED_DUMMY_SECRETS") == "1"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{API}/api/projects/{PROJECT_ID}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {PAT}",
            "Content-Type": "application/json",
        },
    )
    try:
        # Example seed script — API base is a trusted dev/CI env var, not user input.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(req) as r:
            payload = r.read().decode() or "{}"
            return r.status, json.loads(payload)
    except urllib.error.HTTPError as e:
        response_body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(response_body)
        except json.JSONDecodeError:
            return e.code, {"raw": response_body}


class SeedError(Exception):
    """A per-bundle failure. Caught by the run loop so one bad bundle doesn't
    abort the others; the run still exits non-zero at the end."""


def log(slug: str, msg: str) -> None:
    prefix = "[DRY] " if DRY_RUN else "[seed] "
    print(f"{prefix}{slug}: {msg}", flush=True)  # noqa: T201 — CLI script


def die(msg: str) -> None:
    print(f"[seed] FATAL: {msg}", file=sys.stderr, flush=True)  # noqa: T201 — CLI script
    sys.exit(2)


# ---------------------------------------------------------------------------
# Bundle discovery + selection
# ---------------------------------------------------------------------------


def discover_bundles() -> list[Path]:
    """Every immediate subdir of this directory that holds a deployable bundle
    (both `spec.json` and `agent.md`). Sorted by slug for stable output."""
    return sorted(
        (
            d
            for d in EXAMPLES_ROOT.iterdir()
            if d.is_dir() and (d / "spec.json").is_file() and (d / "agent.md").is_file()
        ),
        key=lambda d: d.name,
    )


def select_bundles(bundles: list[Path], selectors: list[str]) -> list[Path]:
    """Filter discovered bundles by selector. A selector matches a bundle whose
    slug equals it or contains it. No selectors -> all bundles."""
    if not selectors:
        return bundles
    chosen: list[Path] = []
    for sel in selectors:
        matches = [b for b in bundles if b.name == sel or sel in b.name]
        if not matches:
            known = ", ".join(b.name for b in bundles)
            print(f"[seed] FATAL: no bundle matches selector {sel!r}; known: {known}", file=sys.stderr)  # noqa: T201
            sys.exit(2)
        for m in matches:
            if m not in chosen:
                chosen.append(m)
    return chosen


# ---------------------------------------------------------------------------
# Spec / bundle loading
# ---------------------------------------------------------------------------


def load_v0_spec(spec_file: Path) -> dict:
    """Load a bundle's spec.json and strip features the platform doesn't accept
    yet (resume block, disallowed trigger config). Auth is multi-mode natively;
    we pass spec.auth.modes through verbatim. `mcps[]` uses the discriminated
    union the platform accepts — destructive remote tools carry inline approval
    gating via `tools[].approval_policy` — so it is NOT stripped here.
    """
    spec = json.loads(spec_file.read_text())

    spec["tools"] = [t for t in spec.get("tools", []) if t.get("kind") in ("native", "custom", "client")]

    # Auth is per-trigger now; there is no spec-level auth. AUTH_MODE overrides
    # each declarative trigger's modes for local testability (`public` to skip
    # auth, `posthog` to require a bearer, etc.). Production leaves the bundle's
    # per-trigger auth in place.
    spec.pop("auth", None)
    auth_override: dict | None = None
    auth_mode_override = os.environ.get("AUTH_MODE")
    if auth_mode_override:
        if auth_mode_override == "shared_secret":
            die("AUTH_MODE=shared_secret requires a header/secret_ref — use the bundle's modes instead")
        if auth_mode_override == "public":
            # Opt-in public exposure must carry the explicit ack field; see
            # AuthModeSchema in services/agent-shared/src/spec/spec.ts.
            auth_override = {"modes": [{"type": "public", "acknowledge_public_exposure": True}]}
        else:
            auth_override = {"modes": [{"type": auth_mode_override}]}

    spec.pop("resume", None)

    for t in spec.get("triggers", []):
        cfg = t.setdefault("config", {})
        allowed = ALLOWED_TRIGGER_CONFIG.get(t.get("type"), set())
        for k in list(cfg.keys()):
            if k not in allowed:
                cfg.pop(k)
        if t.get("type") in DECLARATIVE_TRIGGERS:
            if auth_override is not None:
                t["auth"] = json.loads(json.dumps(auth_override))
            elif "auth" not in t:
                t["auth"] = {"modes": [{"type": "posthog_internal"}]}
        else:
            # Intrinsic-auth triggers (slack / cron) carry no auth modes.
            t.pop("auth", None)

    # MCP URL overrides — let a local seed point at localhost:8787/mcp without
    # editing the canonical bundle. `MCP_URL` rewrites every entry; per-id
    # `MCP_URL_<id>` rewrites only that entry and wins over the bare form.
    bare_override = os.environ.get("MCP_URL")
    for m in spec.get("mcps", []):
        per_id = os.environ.get(f"MCP_URL_{m.get('id', '')}")
        override = per_id or bare_override
        if override:
            m["url"] = override

    return spec


def load_bundle_files(bundle_root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    files["agent.md"] = (bundle_root / "agent.md").read_text()
    skills_dir = bundle_root / "skills"
    if skills_dir.is_dir():
        # Recurse: skills are either flat (`skills/<id>.md`) or nested in their
        # own folder (`skills/<name>/SKILL.md` + companion files). Key each by
        # its full bundle-relative path so `build_typed_bundle` can resolve the
        # body via the spec's `skills[].path` regardless of convention.
        for f in sorted(skills_dir.rglob("*.md")):
            if f.is_file():
                files[f.relative_to(bundle_root).as_posix()] = f.read_text()
    tests_dir = bundle_root / "tests"
    if tests_dir.is_dir():
        for f in sorted(tests_dir.iterdir()):
            if f.is_file() and f.suffix == ".json":
                files[f"tests/{f.name}"] = f.read_text()
    return files


def build_typed_bundle(files: dict[str, str], spec: dict) -> dict:
    """Shape for PUT /bundle/: { agent_md, skills, tools, spec }. The spec slice
    is strict and excludes skills[]/tools[] (derived at freeze)."""
    skills_payload: list[dict] = []
    for skill_ref in spec.get("skills", []):
        skill_id = skill_ref.get("id")
        if not skill_id:
            continue
        path = skill_ref.get("path", f"skills/{skill_id}.md")
        skills_payload.append(
            {
                "id": skill_id,
                "description": skill_ref.get("description", ""),
                "body": files.get(path, ""),
            }
        )
    author_spec = {k: v for k, v in spec.items() if k not in ("skills", "tools")}
    return {"agent_md": files.get("agent.md", ""), "skills": skills_payload, "tools": [], "spec": author_spec}


def per_file_sha256(files: dict[str, str]) -> dict[str, str]:
    """Per-file sha256, mirroring what the janitor stores in its manifest. Used
    to diff against the live revision's manifest for idempotency."""
    return {path: hashlib.sha256(content.encode()).hexdigest() for path, content in files.items()}


def required_secret_keys(spec: dict) -> list[str]:
    """Secret keys a bundle needs set before promote: declared `spec.secrets[]`
    plus per-trigger required keys. Order-preserving + de-duped."""
    keys: list[str] = []
    for s in spec.get("secrets", []) or []:
        key = s.get("key") if isinstance(s, dict) else s
        if isinstance(key, str) and key not in keys:
            keys.append(key)
    for t in spec.get("triggers", []) or []:
        for key in TRIGGER_REQUIRED_SECRETS.get(t.get("type"), []):
            if key not in keys:
                keys.append(key)
    return keys


def ensure_dummy_secrets(slug: str, app_id: str, spec: dict) -> None:
    """Set placeholder values for any required secret not already set. Uses the
    per-key env endpoint so real values (if present) are never overwritten."""
    set_keys: list[str] = []
    for key in required_secret_keys(spec):
        status, payload = _req("GET", f"/agent_applications/{app_id}/env_keys/{key}/")
        if status == 200 and payload.get("is_set"):
            continue
        status, payload = _req("PUT", f"/agent_applications/{app_id}/env_keys/{key}/", {"value": f"placeholder-{key}"})
        if status != 200:
            raise SeedError(f"failed to set placeholder secret {key}: {status} {payload}")
        set_keys.append(key)
    if set_keys:
        log(slug, f"set placeholder secrets: {', '.join(set_keys)}")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def find_or_create_application(slug: str) -> str:
    status, payload = _req("GET", "/agent_applications/")
    if status != 200:
        raise SeedError(f"failed to list applications: {status} {payload}")
    for app in payload.get("results", []):
        if app.get("slug") == slug:
            log(slug, f"application exists: {app['id']}")
            return app["id"]
    meta = METADATA.get(slug, {})
    name = meta.get("name", slug.replace("-", " ").capitalize())
    description = meta.get("description", f"Example agent bundle: {slug}.")
    log(slug, "creating application")
    if DRY_RUN:
        return "dry-run-app-id"
    status, payload = _req(
        "POST",
        "/agent_applications/",
        {"name": name, "slug": slug, "description": description, "archived": False},
    )
    if status not in (200, 201):
        raise SeedError(f"create failed for {slug}: {status} {payload}")
    return payload["id"]


def create_draft(slug: str, app_id: str, parent: str | None, spec: dict) -> str:
    log(slug, f"creating draft (parent={parent or 'none'})")
    if DRY_RUN:
        return "dry-run-rev-id"
    if parent:
        # new_draft branches from the named live revision, copying its bundle.
        # We then overwrite the bundle + patch the spec to match what we want.
        status, payload = _req(
            "POST",
            f"/agent_applications/{app_id}/revisions/new_draft/",
            {"application_id": app_id, "source_revision_id": parent},
        )
        if status not in (200, 201):
            raise SeedError(f"new_draft failed for {slug}: {status} {payload}")
        return payload["revision"]["id"]
    status, payload = _req(
        "POST",
        f"/agent_applications/{app_id}/revisions/",
        {"application_id": app_id, "bundle_uri": f"local://{slug}/seed", "spec": spec},
    )
    if status not in (200, 201):
        raise SeedError(f"draft create failed for {slug}: {status} {payload}")
    return payload["id"]


def push_bundle(slug: str, app_id: str, rev_id: str, files: dict[str, str], spec: dict) -> None:
    typed = build_typed_bundle(files, spec)
    log(
        slug,
        f"pushing typed bundle (agent_md={len(typed['agent_md'])}c, "
        f"skills={len(typed['skills'])}, tools={len(typed['tools'])})",
    )
    if DRY_RUN:
        return
    status, payload = _req("PUT", f"/agent_applications/{app_id}/revisions/{rev_id}/bundle/", typed)
    if status != 200:
        raise SeedError(f"bundle update failed for {slug}: {status} {payload}")


def patch_spec(slug: str, app_id: str, rev_id: str, spec: dict) -> None:
    log(slug, "patching spec")
    if DRY_RUN:
        return
    status, payload = _req("PATCH", f"/agent_applications/{app_id}/revisions/{rev_id}/", {"spec": spec})
    if status not in (200, 202):
        raise SeedError(f"spec patch failed for {slug}: {status} {payload}")


def validate(slug: str, app_id: str, rev_id: str) -> None:
    log(slug, "validating")
    if DRY_RUN:
        return
    status, payload = _req("POST", f"/agent_applications/{app_id}/revisions/{rev_id}/validate/")
    if status != 200 or not payload.get("ok", False):
        raise SeedError(f"validate failed for {slug}: {status} {json.dumps(payload, indent=2)}")
    log(slug, f"  ok: {len(payload.get('resolved_natives', []))} natives resolved")


def freeze(slug: str, app_id: str, rev_id: str) -> str:
    log(slug, "freezing")
    if DRY_RUN:
        return "dry-run-sha"
    status, payload = _req("POST", f"/agent_applications/{app_id}/revisions/{rev_id}/freeze/")
    if status != 200:
        raise SeedError(f"freeze failed for {slug}: {status} {payload}")
    return payload.get("bundle_sha256", "")


def promote(slug: str, app_id: str, rev_id: str) -> None:
    log(slug, f"promoting {rev_id} -> live")
    if DRY_RUN:
        return
    status, payload = _req("POST", f"/agent_applications/{app_id}/revisions/{rev_id}/promote/")
    if status != 200:
        raise SeedError(f"promote failed for {slug}: {status} {payload}")


def get_live(app_id: str) -> tuple[str | None, dict[str, str] | None, dict | None]:
    """Returns (live_revision_id, {path: sha256}, spec) or (None, None, None)."""
    status, payload = _req("GET", f"/agent_applications/{app_id}/")
    if status != 200:
        return None, None, None
    rev_id = payload.get("live_revision")
    if not rev_id:
        return None, None, None
    status, rev = _req("GET", f"/agent_applications/{app_id}/revisions/{rev_id}/")
    spec = rev.get("spec") if status == 200 else None
    status, manifest = _req("GET", f"/agent_applications/{app_id}/revisions/{rev_id}/manifest/")
    if status != 200:
        return rev_id, None, spec
    return rev_id, {f["path"]: f["sha256"] for f in manifest.get("files", [])}, spec


def seed_bundle(bundle_root: Path) -> None:
    """Run the full deploy pipeline for one bundle. Raises SystemExit (via die)
    on any platform/validation error."""
    slug = bundle_root.name
    spec = load_v0_spec(bundle_root / "spec.json")
    files = load_bundle_files(bundle_root)
    target_manifest = per_file_sha256(files)
    log(slug, f"target bundle: {len(files)} files")

    app_id = find_or_create_application(slug)
    if SEED_DUMMY_SECRETS and not DRY_RUN:
        ensure_dummy_secrets(slug, app_id, spec)
    if DRY_RUN:
        log(slug, "would deploy: draft -> bundle -> spec -> validate -> freeze -> promote")
        return

    live_rev, live_manifest, live_spec = get_live(app_id)
    log(slug, f"current live: rev={live_rev}")

    if live_rev and live_manifest == target_manifest and live_spec == spec:
        log(slug, "bundle manifest AND spec match live — no-op")
        return
    if live_rev and live_manifest == target_manifest and live_spec != spec:
        log(slug, "bundle matches but spec drifted — re-promoting")
    elif live_rev and live_manifest != target_manifest:
        log(slug, "bundle drifted — re-promoting")

    rev_id = create_draft(slug, app_id, parent=live_rev, spec=spec)
    push_bundle(slug, app_id, rev_id, files, spec)
    patch_spec(slug, app_id, rev_id, spec)
    validate(slug, app_id, rev_id)
    new_sha = freeze(slug, app_id, rev_id)
    log(slug, f"frozen sha={new_sha[:12]}...")
    promote(slug, app_id, rev_id)
    log(slug, f"DONE: live at {rev_id}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> tuple[bool, list[str]]:
    """Returns (list_only, selectors). Accepts positional selectors and the
    `--only a,b` / `--list` flags."""
    list_only = False
    selectors: list[str] = []
    for arg in argv:
        if arg == "--list":
            list_only = True
        elif arg.startswith("--only="):
            selectors.extend(s for s in arg.split("=", 1)[1].split(",") if s)
        elif arg == "--only":
            die("--only needs a value, e.g. --only=agent-concierge")
        elif arg.startswith("--"):
            die(f"unknown flag {arg!r}")
        else:
            selectors.append(arg)
    return list_only, selectors


def mint_dev_pat() -> str | None:
    """Mint (idempotently) the deterministic local-dev personal API key via the
    same helper `hogli dev:api-key` uses — `manage.py setup_local_api_key` — and
    return its value, adding the agents scopes the seed needs. Dev-only; returns
    None if it can't (no flox, command failed, no users). Lets `seed.py` run
    without the caller hunting down a PAT."""
    repo_root = EXAMPLES_ROOT.parents[3]
    try:
        out = subprocess.run(
            [
                "flox",
                "activate",
                "--",
                "python",
                "manage.py",
                "setup_local_api_key",
                "--add-scopes",
                "agents:read",
                "agents:write",
                "project:read",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log("pat", f"auto-mint failed to run setup_local_api_key: {e}")
        return None
    if out.returncode != 0:
        log("pat", f"setup_local_api_key exited {out.returncode}: {out.stderr.strip().splitlines()[-1:] or ''}")
        return None
    # The command prints `Key: <value>` as its last meaningful line.
    for line in reversed(out.stdout.splitlines()):
        line = line.strip()
        if line.startswith("Key:"):
            return line.split("Key:", 1)[1].strip()
    return None


def main() -> None:
    global PAT
    list_only, selectors = parse_args(sys.argv[1:])
    bundles = discover_bundles()
    if not bundles:
        die(f"no bundles found under {EXAMPLES_ROOT}")

    selected = select_bundles(bundles, selectors)

    if list_only:
        print(f"Discovered {len(bundles)} bundle(s) under {EXAMPLES_ROOT}:")  # noqa: T201
        for b in bundles:
            mark = "*" if b in selected else " "
            print(f"  [{mark}] {b.name}")  # noqa: T201
        return

    if not PAT:
        print("[seed] no PAT set — minting the local dev key via setup_local_api_key…")  # noqa: T201
        PAT = mint_dev_pat()
    if not PAT:
        print(  # noqa: T201
            "[seed] FATAL: no PAT. Set PAT=phx_… or run in a flox env where "
            "`manage.py setup_local_api_key` can mint the local dev key.",
            file=sys.stderr,
        )
        sys.exit(2)

    print(  # noqa: T201
        f"[seed] target: {API} project={PROJECT_ID} — "
        f"{len(selected)}/{len(bundles)} bundle(s): {', '.join(b.name for b in selected)}"
    )
    # Continue past a failing bundle so one that needs secrets (or otherwise
    # can't promote) doesn't block the rest; report + exit non-zero at the end.
    failures: list[tuple[str, str]] = []
    for bundle_root in selected:
        try:
            seed_bundle(bundle_root)
        except SeedError as e:
            log(bundle_root.name, f"FAILED — {e}")
            failures.append((bundle_root.name, str(e)))

    ok = len(selected) - len(failures)
    print(f"[seed] done: {ok}/{len(selected)} bundle(s) succeeded")  # noqa: T201
    if failures:
        print("[seed] failed bundles:", file=sys.stderr)  # noqa: T201
        for slug, msg in failures:
            print(f"  - {slug}: {msg.splitlines()[0]}", file=sys.stderr)  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
