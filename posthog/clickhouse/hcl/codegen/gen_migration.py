#!/usr/bin/env python3
"""Generate a ClickHouse migration from a declarative-HCL change.

Placement comes from **composition**, not a side-table: for every (env, role) node
in the manifest (`../nodes`) this diffs the committed layer stack against the working
tree with `hclexp diff -format json` and collects the structured, dependency-ordered
operations. Each operation already carries everything we need — no text parsing:

  kind / object / sql           the DDL statement and what it does
  engine / replicated           used to derive the targeting below
  order                         hclexp's per-node dependency order (preserved)
  unsafe / unsafe_reason        recreate-only changes, surfaced as review notes

Targeting is then derived per statement:

  node_roles                    = the roles whose composition surfaced the statement
                                  (shared objects -> every role; OPS-only -> [OPS])
  is_alter_on_replicated_table  = ALTER on a Replicated* MergeTree (from `replicated`)
  sharded                       = replicated AND on the multi-shard DATA cluster
  env-specific statements       = flagged for settings.CLOUD_DEPLOYMENT gating

Output is the `operations = [...]` body for a numbered migration.

Usage (from the repo root):
  python posthog/clickhouse/hcl/codegen/gen_migration.py --name add_foo
  # --ref <git-ref> (default HEAD), --out <path|-> (default stdout), --auto
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))  # .../posthog/clickhouse/hcl/codegen
HCL_DIR = os.path.dirname(HERE)  # .../posthog/clickhouse/hcl
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
HCL_REL = os.path.relpath(HCL_DIR, REPO_ROOT)  # posthog/clickhouse/hcl
MANIFEST = os.path.join(HCL_DIR, "nodes")
# absolute path to the wrapper (lives at hcl/bin/hclexp); subprocess won't resolve a relative exec via cwd
HCLEXP = os.path.join(HCL_DIR, "bin", "hclexp")

# Canonical role order for emitted node_roles (mirrors ALL_ROLES in migration 0273).
# Only roles present in the manifest appear; the rest are listed for stable ordering
# if/when they are uncommented there.
ROLE_ORDER = ["data", "endpoints", "aux", "ai_events", "sessions", "logs", "ops"]


def read_manifest() -> list[tuple[str, str, list[str]]]:
    out = []
    for line in open(MANIFEST):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        out.append((parts[0], parts[1], parts[2:]))
    return out


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def stack(root: str, layers: list[str]) -> str:
    return ",".join(os.path.join(root, HCL_REL, layer) for layer in layers)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--out", default="-")
    ap.add_argument(
        "--auto",
        action="store_true",
        help="write the next numbered migration into posthog/clickhouse/migrations/ and bump max_migration.txt",
    )
    args = ap.parse_args()

    manifest = read_manifest()
    envs_for_role: dict[str, set[str]] = {}
    for env, role, _ in manifest:
        envs_for_role.setdefault(role, set()).add(env)

    with tempfile.TemporaryDirectory() as tmp:
        # Materialize the committed tree so the left side resolves the reference layers.
        tar = subprocess.run(
            ["git", "archive", args.ref, HCL_REL], cwd=REPO_ROOT, capture_output=True, check=True
        ).stdout
        subprocess.run(["tar", "-x", "-C", tmp], input=tar, check=True)

        # stmt -> {op, roles, envs}; identical SQL across nodes dedupes to one op.
        merged: dict[str, dict] = {}
        # stmt -> (manifest_index, per-node order): first-seen global order. Within a
        # node hclexp orders by dependency; across nodes we keep manifest order. (True
        # cross-role ordering would need hclexp's dump-based `plan`, which doesn't apply
        # to a committed-vs-working diff — our managed roles are independent anyway.)
        order_key: dict[str, tuple[int, int]] = {}
        unsafe_notes: dict[str, str] = {}  # object -> reason (recreate-only changes)
        for idx, (env, role, layers) in enumerate(manifest):
            left = stack(tmp, layers)
            right = stack(REPO_ROOT, layers)
            data = json.loads(run([HCLEXP, "diff", "-left", left, "-right", right, "-format", "json"]))
            for op in data.get("operations") or []:
                sql = op["sql"]
                entry = merged.setdefault(sql, {"op": op, "roles": set(), "envs": set()})
                entry["roles"].add(role)
                entry["envs"].add(env)
                order_key.setdefault(sql, (idx, op["order"]))
            for u in data.get("unsafe") or []:
                unsafe_notes.setdefault(u["object"], u["reason"])

    if not merged:
        raise SystemExit("No DDL generated — the HCL has no changes vs the ref.")

    notes = [f"# UNSAFE (review/recreate by hand): {obj} — {reason}" for obj, reason in sorted(unsafe_notes.items())]
    operations = []
    for sql in sorted(merged, key=lambda s: order_key[s]):
        entry = merged[sql]
        op, roles, envs = entry["op"], entry["roles"], entry["envs"]
        node_roles = [r for r in ROLE_ORDER if r in roles]
        replicated = op["replicated"]
        is_alter_repl = op["kind"] == "ALTER" and replicated
        sharded = replicated and "data" in roles
        # Env-specific if the statement is absent from some env that hosts these roles.
        full_envs = set().union(*(envs_for_role[r] for r in roles))
        gate = "" if envs >= full_envs else f"  # NOTE: only {sorted(envs)} — gate with settings.CLOUD_DEPLOYMENT"
        roles_src = "[" + ", ".join(f"NodeRole.{r.upper()}" for r in node_roles) + "]"
        operations.append(
            "    run_sql_with_exceptions(\n"
            f"        {sql!r},\n"
            f"        node_roles={roles_src},{gate}\n"
            f"        sharded={sharded},\n"
            f"        is_alter_on_replicated_table={is_alter_repl},\n"
            "    ),"
        )

    body = (
        '"""AUTO-GENERATED from the declarative HCL by '
        "posthog/clickhouse/hcl/codegen/gen_migration.py.\n"
        "Placement (node_roles) is derived from the node composition manifest; review before committing.\n"
        '"""\n'
        "from posthog.clickhouse.client.connection import NodeRole\n"
        "from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions\n\n"
    )
    if notes:
        body += "\n".join(notes) + "\n\n"
    body += "operations = [\n" + "\n".join(operations) + "\n]\n"

    if args.auto:
        mig_dir = os.path.join(REPO_ROOT, "posthog", "clickhouse", "migrations")
        max_file = os.path.join(mig_dir, "max_migration.txt")
        last = open(max_file).read().strip()
        num = int(re.match(r"(\d+)", last).group(1)) + 1
        name = f"{num:04d}_{args.name}"
        path = os.path.join(mig_dir, f"{name}.py")
        if os.path.exists(path):
            raise SystemExit(f"ERROR: {path} already exists")
        open(path, "w").write(body)
        open(max_file, "w").write(name + "\n")
        sys.stderr.write(f"wrote {os.path.relpath(path, REPO_ROOT)}\nbumped max_migration.txt -> {name}\n")
    elif args.out == "-":
        sys.stdout.write(body)
    else:
        open(args.out, "w").write(body)
        sys.stderr.write(f"wrote {args.out}\n")


if __name__ == "__main__":
    main()
