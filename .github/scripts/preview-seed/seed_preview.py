#!/usr/bin/env python3
# ruff: noqa: T201 — standalone CLI payload, print is the output channel
"""Seed a hogbox preview box with the dashboard-colors comparison dataset.

TEMPORARY tooling for the PR #74534 / #74545 preview comparison — remove this
directory (and the workflow step invoking it) before merging either PR.

Runs on the CI runner from tools/hogbox-preview (hogland SDK + HOG_TOKEN /
HOG_OIDC_AUDIENCE already in the deploy job's scope). Attaches to the live
preview box by pen name, then:

1. adds PERSISTED_FEATURE_FLAGS=dashboard-colors to the compose override and
   recreates web — the box's UI evaluates flags against PostHog Cloud, where
   the demo user matches no condition, so the flag must be forced box-locally,
2. ships the payload into the bind-mounted posthog/ source dir,
3. inserts synthetic events/persons straight into ClickHouse/Postgres via the
   web image (posthog.local_bootstrap.importer — no ingestion pipeline runs on
   preview boxes),
4. mints a personal API key via the seeded demo login, then recreates the
   comparison dashboard from the fixture over REST in-box, clears the team's
   test-account filters, and force-refreshes every tile so it opens warm.
"""

import os
import re
import sys
import shlex
import pathlib
import argparse

REPO = "/home/hog/posthog"
COMPOSE = f"cd {REPO} && docker compose -f docker-compose.dev-full.yml -f docker-compose.preview.yml"
PAYLOAD_FILES = ("generate_events.py", "recreate_dashboard.py", "dashboard-fixture.json")
FLAG_ENV_LINE = "      - PERSISTED_FEATURE_FLAGS=dashboard-colors"

# Mirrors stack.py's deep-health probe: everything runs inside the box against
# localhost:8000, one cookie jar for csrf + session.
API_KEY_SCRIPT = """
set -eu
jar=$(mktemp)
base=http://localhost:8000
curl -sf -m 30 -c "$jar" -o /dev/null "$base/login"
csrf=$(awk '/csrftoken/ {print $7}' "$jar" | tail -n1)
curl -sf -m 30 -b "$jar" -c "$jar" -X POST -H 'Content-Type: application/json' \
  -H "X-CSRFToken: $csrf" -H "Referer: $base/" \
  -d '{"email":"test@posthog.com","password":"12345678"}' -o /dev/null "$base/api/login/"
csrf=$(awk '/csrftoken/ {print $7}' "$jar" | tail -n1)
resp=$(curl -sf -m 30 -b "$jar" -X POST -H 'Content-Type: application/json' \
  -H "X-CSRFToken: $csrf" -H "Referer: $base/" \
  -d '{"label":"preview-seed","scopes":["*"]}' "$base/api/personal_api_keys/")
echo "APIKEY=$(printf '%s' "$resp" | sed -n 's/.*"value":"\\([^"]*\\)".*/\\1/p')"
"""


def log(msg: str) -> None:
    print(f"[preview-seed] {msg}", file=sys.stderr, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--name", required=True, help="pen name, e.g. preview-pr-74534")
    ap.add_argument("--payload-dir", required=True)
    args = ap.parse_args()

    sys.path.insert(0, os.getcwd())  # tools/hogbox-preview, for the hogbox_preview package
    from hogbox_preview.hogland_backend import HoglandBackend

    payload = pathlib.Path(args.payload_dir)
    backend = HoglandBackend(host=args.host, name=args.name)
    log(f"attaching to {args.name}")
    backend.attach()

    # 1. Force the dashboard-colors flag via the persisted-flags mechanism.
    override_path = f"{REPO}/docker-compose.preview.yml"
    override = backend.exec(f"cat {override_path}", timeout=60).stdout
    if FLAG_ENV_LINE.strip() not in override:
        lines = override.splitlines()
        anchor = next(i for i, line in enumerate(lines) if line.strip().startswith("- SECRET_KEY="))
        lines.insert(anchor + 1, FLAG_ENV_LINE)
        backend.write_file(override_path, "\n".join(lines) + "\n")
        log("override updated with PERSISTED_FEATURE_FLAGS; recreating web")
        # Clean `up` recreates web for the env change (never `restart` — the
        # Unit listener gotcha documented in stack.py).
        backend.run_long(f"{COMPOSE} up -d --no-build web", name="seed-flag-web", timeout=900)
        backend.wait_http_ok("/_health", expect=200, timeout=900)
    else:
        log("persisted flag already present in override")

    # 2. Ship the payload into the bind-mounted backend source.
    backend.exec(f"mkdir -p {REPO}/posthog/tmp_seed", timeout=60)
    for fname in PAYLOAD_FILES:
        backend.write_file(f"{REPO}/posthog/tmp_seed/{fname}", (payload / fname).read_bytes())
    log("payload shipped to posthog/tmp_seed/")

    # 3. Synthetic events + persons, straight into CH/PG (idempotent).
    log("inserting synthetic events (this wipes previous synth-% rows)")
    # PYTHONPATH: the script lives at /code/posthog/tmp_seed/, so sys.path[0] is
    # the script dir, not /code — `import posthog` needs /code on the path.
    r = backend.run_long(
        f"{COMPOSE} run --rm -T -e PYTHONPATH=/code web python posthog/tmp_seed/generate_events.py",
        name="seed-events",
        timeout=1500,
    )
    log(f"events done: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else 'no output'}")

    # 4. Personal API key via the demo session, then the dashboard.
    r = backend.exec(API_KEY_SCRIPT, timeout=120)
    match = re.search(r"APIKEY=(\S+)", r.stdout)
    if not match:
        raise RuntimeError(f"could not mint a personal API key:\n{r.stdout}\n{r.stderr}")
    api_key = match.group(1)
    log("personal API key minted; creating dashboard + refreshing tiles")
    r = backend.run_long(
        f"{COMPOSE} run --rm -T -e PYTHONPATH=/code web python posthog/tmp_seed/recreate_dashboard.py "
        f"posthog/tmp_seed/dashboard-fixture.json --host http://web:8000 "
        f"--api-key {shlex.quote(api_key)} --replace --clear-test-filters --refresh",
        name="seed-dashboard",
        timeout=1800,
    )
    tail = "\n".join(r.stdout.strip().splitlines()[-5:])
    log(f"dashboard done:\n{tail}")
    log("seed complete")


if __name__ == "__main__":
    main()
