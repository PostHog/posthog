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
    PAT=phx_... python services/agent-tests/src/examples/seed.py builder approval

    # Same, comma-separated:
    PAT=phx_... python services/agent-tests/src/examples/seed.py --only agent-builder,agent-approval-demo

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
                   (PostHog MCPs — auth.provider=posthog — otherwise default to
                   the MCP host for POSTHOG_API's region: local / us / eu.)

Exit codes:
    0  every selected bundle deployed / re-promoted / no-op
    1  one or more bundles failed (validation or platform error)
    2  bad env / missing PAT / unknown selector
"""

from __future__ import annotations

import io
import os
import re
import sys
import json
import hashlib
import zipfile
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

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
    "agent-builder": {
        "name": "Agent Builder",
        "description": "Meta-agent for the platform.",
    },
}

# Trigger config fields the Django write-schema accepts today. It intentionally
# lags the zod schema for some fields (e.g. chat/mcp `allow_restart`), so we
# strip anything not listed here before writing. Keep aligned with
# `products/agent_platform/backend/spec_schema.py`, not just `spec.ts`.
# Triggers that carry their own per-trigger `auth` block. Intrinsic triggers
# (slack / cron) are gated differently (signing secret / internal) and carry no
# auth modes. Mirrors the declarative/intrinsic split in `spec.ts`.
DECLARATIVE_TRIGGERS: set[str] = {"webhook", "chat", "mcp"}


def _load_trigger_required_secrets() -> dict[str, list[str]]:
    """Required secret keys per trigger type, read from the checked-in
    generated artifact (`trigger_required_secrets.generated.json`, emitted
    from `services/agent-shared/src/spec/trigger-secrets.ts`) rather than
    hand-copied — the same registry `backend/logic/spec_schema.py`'s promote
    gate reads via `backend/logic/generated.py`. Only `required: true`
    entries block promote, matching that gate's filter. Used only by the
    optional SEED_DUMMY_SECRETS placeholder path below."""
    backend_logic_dir = next(
        (p / "backend" / "logic" for p in EXAMPLES_ROOT.parents if (p / "backend" / "logic").is_dir()),
        None,
    )
    if backend_logic_dir is None:
        raise RuntimeError("couldn't locate products/agent_platform/backend/logic from seed.py's path")
    artifact = backend_logic_dir / "trigger_required_secrets.generated.json"
    raw: dict[str, list[dict[str, object]]] = json.loads(artifact.read_text(encoding="utf-8"))
    return {
        trigger_type: [str(r["key"]) for r in requirements if r.get("required")]
        for trigger_type, requirements in raw.items()
    }


TRIGGER_REQUIRED_SECRETS: dict[str, list[str]] = _load_trigger_required_secrets()

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


def _req_multipart(path: str, filename: str, content: bytes, content_type: str) -> tuple[int, dict]:
    """POST a single-file multipart/form-data body (form field `file`). The skill
    store's `import` endpoint takes a zip this way; urllib has no multipart helper
    so we frame the body by hand with a fixed boundary."""
    boundary = "----seedpyboundary7MA4YWxkTrZu0gW"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    body = head + content + f"\r\n--{boundary}--\r\n".encode()
    url = f"{API}/api/projects/{PROJECT_ID}{path}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {PAT}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
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
    """Load a bundle's spec.json and apply local-dev-only overrides. The spec
    is otherwise passed through verbatim — the platform's own write-time
    validation (`AGENT_SPEC_JSON_SCHEMA_FOR_WRITE`, mirrored from the canonical
    zod `AgentSpecSchema`) is the single source of truth for what's accepted,
    so an unsupported field fails loudly at deploy rather than being silently
    dropped here. The only mutations are the `AUTH_MODE` per-trigger auth
    override and the `MCP_URL` rewrites, both purely for local testing.
    """
    spec = json.loads(spec_file.read_text())

    # AUTH_MODE overrides each declarative trigger's modes for local
    # testability (`public` to skip auth, `posthog` to require a bearer, etc.).
    # Production leaves the bundle's per-trigger auth in place.
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

    for t in spec.get("triggers", []):
        if t.get("type") in DECLARATIVE_TRIGGERS:
            if auth_override is not None:
                t["auth"] = json.loads(json.dumps(auth_override))
            elif "auth" not in t:
                t["auth"] = {"modes": [{"type": "posthog_internal"}]}
        else:
            # Intrinsic-auth triggers (slack / cron) carry no auth modes.
            t.pop("auth", None)

    # MCP URL resolution. A PostHog MCP (one authed by the `posthog` identity
    # provider) tracks the seed target's region by default — localhost when
    # seeding locally, the us/eu cloud MCP when seeding to those hosts — so the
    # canonical bundle ships the localhost URL and still works in every env.
    # Explicit overrides win: `MCP_URL` rewrites every entry, per-id
    # `MCP_URL_<id>` rewrites only that entry and beats the bare form.
    bare_override = os.environ.get("MCP_URL")
    region_mcp_url = posthog_mcp_url_for_target(API)
    for m in spec.get("mcps", []):
        per_id = os.environ.get(f"MCP_URL_{m.get('id', '')}")
        if per_id:
            m["url"] = per_id
        elif bare_override:
            m["url"] = bare_override
        elif isinstance(m.get("auth"), dict) and m["auth"].get("provider") == "posthog":
            m["url"] = region_mcp_url

    return spec


def posthog_mcp_url_for_target(api_base: str) -> str:
    """The PostHog MCP URL matching the seed target: local → the local MCP, the
    us/eu cloud hosts → their region MCP, anything else → the region-agnostic
    host. Default for `posthog`-authed MCP entries; explicit MCP_URL wins."""
    host = (urlparse(api_base).hostname or "").lower()
    if host in ("localhost", "127.0.0.1") or host.endswith(".localhost"):
        return "http://localhost:8787/mcp"
    if "eu.posthog.com" in host:
        return "https://mcp.eu.posthog.com/mcp"
    if "us.posthog.com" in host or "app.posthog.com" in host:
        return "https://mcp.us.posthog.com/mcp"
    return "https://mcp.posthog.com/mcp"


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


def ensure_dummy_secrets(slug: str, app_id: str, rev_id: str, spec: dict) -> None:
    """Set placeholder values for any required secret not already set. `encrypted_env`
    lives on the revision, so this targets the per-revision env endpoint and must
    run after the draft exists and before promote (the promote gate reads it).
    Never overwrites a real value (the GET `is_set` check)."""
    base = f"/agent_applications/{app_id}/revisions/{rev_id}/env_keys"
    set_keys: list[str] = []
    for key in required_secret_keys(spec):
        status, payload = _req("GET", f"{base}/{key}/")
        if status == 200 and payload.get("is_set"):
            continue
        status, payload = _req("PUT", f"{base}/{key}/", {"value": f"placeholder-{key}"})
        if status != 200:
            raise SeedError(f"failed to set placeholder secret {key}: {status} {payload}")
        set_keys.append(key)
    if set_keys:
        log(slug, f"set placeholder secrets: {', '.join(set_keys)}")


# ---------------------------------------------------------------------------
# Store skills
#
# The skill store is canonical: a frozen revision pulls each skill from the
# `llm_skills` store via `skill_refs`, and freeze REFUSES inline skills that
# aren't backed by a store reference. So before freeze we mirror every bundle
# skill into the store (idempotent, by name) and set the draft's `skill_refs`.
# The store name and the bundle folder id (the ref `alias`) are both the spec
# skill id — example skill ids are unique across bundles.
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def skill_md_for_store(skill_id: str, description: str, body: str) -> str:
    """The SKILL.md text to import, guaranteed to carry a `name` (the store
    requires it). Three cases across the example bundles:
      - no frontmatter (starts at a heading) → synthesise the whole block;
      - frontmatter with a `description` but no `name` → inject `name`;
      - frontmatter with both → use verbatim.
    Synthesised values come from the spec (skill id + ref description) and are
    JSON-encoded — valid YAML double-quoted scalars — so colons / em-dashes in
    descriptions can't break the block."""
    match = _FRONTMATTER_RE.match(body)
    if match is None:
        return f"---\nname: {json.dumps(skill_id)}\ndescription: {json.dumps(description)}\n---\n\n{body}"
    if re.search(r"(?m)^name:[ \t]*\S", match.group(0)):
        return body
    # Frontmatter present but unnamed — inject `name` right after the opening `---`.
    return body.replace("---\n", f"---\nname: {json.dumps(skill_id)}\n", 1)


def build_skill_zip(skill_id: str, skill_md: str, companions: dict[str, str]) -> bytes:
    """A spec-compliant skill zip: `<id>/SKILL.md` plus any companion files under
    the same folder. `parse_skill_zip` finds the single SKILL.md and collects its
    siblings."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{skill_id}/SKILL.md", skill_md)
        for rel_path, content in companions.items():
            archive.writestr(f"{skill_id}/{rel_path}", content)
    return buf.getvalue()


def _post_frontmatter_body(body: str) -> str:
    """The body the store keeps (frontmatter stripped), for drift comparison."""
    match = _FRONTMATTER_RE.match(body)
    return (body[match.end() :] if match else body).strip()


def ensure_store_skill(slug: str, skill_id: str, description: str, body: str, companions: dict[str, str]) -> str:
    """Find-or-create the bundle skill in the `llm_skills` store, publishing a new
    version when its body/description has drifted — freeze pulls the store copy, so
    a stale store skill would ship instead of the bundle's. Returns the store name."""
    want_body = _post_frontmatter_body(body)
    want_desc = (description or "").strip()
    status, existing = _req("GET", f"/llm_skills/name/{skill_id}/")
    if status == 200:
        if (existing.get("body") or "").strip() == want_body and (
            existing.get("description") or ""
        ).strip() == want_desc:
            return skill_id
        ver = existing.get("version")
        status, payload = _req(
            "PATCH",
            f"/llm_skills/name/{skill_id}/",
            {"base_version": ver, "body": want_body, "description": want_desc},
        )
        if status not in (200, 201):
            raise SeedError(f"skill update failed for '{skill_id}': {status} {payload}")
        log(slug, f"updated store skill '{skill_id}' (v{ver} → v{payload.get('version', '?')})")
        return skill_id
    skill_md = skill_md_for_store(skill_id, description, body)
    zip_bytes = build_skill_zip(skill_id, skill_md, companions)
    status, payload = _req_multipart("/llm_skills/import/", f"{skill_id}.zip", zip_bytes, "application/zip")
    if status in (200, 201):
        return str(payload.get("name") or skill_id)
    # A name conflict means a concurrent/prior run already created it — reuse.
    if status == 400 and "already exists" in json.dumps(payload):
        return skill_id
    raise SeedError(f"skill import failed for '{skill_id}': {status} {payload}")


def set_skill_refs(slug: str, app_id: str, rev_id: str, refs: list[dict]) -> None:
    """Full-replace the draft's store-skill references (resolved + materialised at
    freeze). No-op when the bundle has no skills."""
    if not refs:
        return
    log(slug, f"setting {len(refs)} skill ref(s): {', '.join(r['alias'] for r in refs)}")
    status, payload = _req("PUT", f"/agent_applications/{app_id}/revisions/{rev_id}/skill_refs/", {"skill_refs": refs})
    if status != 200:
        raise SeedError(f"set skill_refs failed for {slug}: {status} {payload}")


def seed_store_skills(slug: str, app_id: str, rev_id: str, spec: dict, bundle_root: Path) -> None:
    """Mirror every bundle skill into the store and pin the draft's `skill_refs`,
    so freeze can resolve them. `from_template` is the store name; `alias` is the
    bundle folder id — both the spec skill id here."""
    refs: list[dict] = []
    for skill_ref in spec.get("skills", []) or []:
        skill_id = skill_ref.get("id")
        if not skill_id:
            continue
        rel = skill_ref.get("path", f"skills/{skill_id}.md")
        skill_md_path = bundle_root / rel
        body = skill_md_path.read_text() if skill_md_path.is_file() else ""
        # Companions: every sibling file in the skill's folder except SKILL.md.
        companions: dict[str, str] = {}
        skill_dir = skill_md_path.parent
        if skill_dir.is_dir() and skill_dir != bundle_root:
            for f in sorted(skill_dir.rglob("*")):
                if f.is_file() and f != skill_md_path:
                    companions[f.relative_to(skill_dir).as_posix()] = f.read_text()
        store_name = ensure_store_skill(slug, skill_id, skill_ref.get("description", ""), body, companions)
        refs.append({"from_template": store_name, "alias": skill_id})
    set_skill_refs(slug, app_id, rev_id, refs)


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
    # Mirror bundle skills into the store + pin skill_refs BEFORE freeze — the
    # freeze gate refuses inline skills that lack a store reference.
    seed_store_skills(slug, app_id, rev_id, spec, bundle_root)
    if SEED_DUMMY_SECRETS:
        ensure_dummy_secrets(slug, app_id, rev_id, spec)
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
            die("--only needs a value, e.g. --only=agent-builder")
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
    # The repo root is the ancestor that holds `manage.py` — find it rather than
    # hardcoding a parent index, which silently breaks if this file ever moves.
    repo_root = next(
        (p for p in EXAMPLES_ROOT.parents if (p / "manage.py").is_file()),
        None,
    )
    if repo_root is None:
        log("pat", "couldn't locate repo root (no manage.py in any parent dir)")
        return None
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
