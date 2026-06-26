#!/usr/bin/env python3
"""Generate a ClickHouse migration from a declarative-HCL change.

Uses `hclexp plan` to diff the **committed goldens** (current managed state) against
the **working-tree composition** (desired) for every role at once, per env. Because
goldens hold only the managed set, a DROP here is a real removal — there is no live
cluster and nothing unmanaged to prune. `plan` unions roles and orders statements by
cross-role dependency, so each operation already carries everything we need — no text
parsing:

  sql / kind / object           the DDL statement and what it does
  roles                         which node roles surfaced it (union across the env)
  engine / replicated           used to derive the targeting below
  order                         hclexp's cross-role dependency order
  unsafe / unsafe_reason        recreate-only changes, surfaced as review notes

For each env in the manifest we feed plan a -dump built from that env's committed
goldens (tagged with hostClusterRole) and resolve the desired side from the working
layers. Results are merged across envs to derive:

  node_roles                    = roles, ordered by ROLE_ORDER
  is_alter_on_replicated_table  = ALTER on a Replicated* MergeTree (from `replicated`)
  sharded                       = replicated AND on the multi-shard DATA cluster
  env-specific statements       = present in only some envs -> CLOUD_DEPLOYMENT gating

Output is the `operations = [...]` body for a numbered migration.

Usage (from the repo root):
  python posthog/clickhouse/hcl/codegen/gen_migration.py --name add_foo
  # --ref <git-ref> (default HEAD, the golden baseline), --out <path|->, --auto
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import tempfile
import subprocess
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))  # .../posthog/clickhouse/hcl/codegen
HCL_DIR = os.path.dirname(HERE)  # .../posthog/clickhouse/hcl
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
HCL_REL = os.path.relpath(HCL_DIR, REPO_ROOT)  # posthog/clickhouse/hcl (relative: resolves inside the wrapper)
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


def write_manifest_hcl(manifest: list[tuple[str, str, list[str]]], path: str) -> None:
    """Render the `nodes` text manifest as the HCL manifest `plan` expects (role-first)."""
    roles: OrderedDict[str, list[tuple[str, list[str]]]] = OrderedDict()
    for env, role, layers in manifest:
        roles.setdefault(role, []).append((env, layers))
    lines = []
    for role, envs in roles.items():
        lines.append(f'role "{role}" {{')
        for env, layers in envs:
            lst = ", ".join(f'"{layer}"' for layer in layers)
            lines.append(f'  env "{env}" {{ layers = [{lst}] }}')
        lines.append("}")
    open(path, "w").write("\n".join(lines) + "\n")


def write_dump(env: str, roles: list[str], ref: str, dump_dir: str) -> None:
    """Build plan's -dump for one env from the committed goldens, tagged by role."""
    os.makedirs(dump_dir)
    for role in roles:
        golden = run(["git", "show", f"{ref}:{HCL_REL}/golden/{env}-{role}.hcl"])
        with open(os.path.join(dump_dir, f"{role}.hcl"), "w") as f:
            f.write(f'node "{role}" {{\n  macros = {{ hostClusterRole = "{role}" }}\n}}\n')
            f.write(golden)


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
    env_roles: OrderedDict[str, list[str]] = OrderedDict()  # env -> roles, in manifest order
    for env, role, _ in manifest:
        envs_for_role.setdefault(role, set()).add(env)
        env_roles.setdefault(env, [])
        if role not in env_roles[env]:
            env_roles[env].append(role)

    # stmt -> {op, roles, envs}; identical SQL across envs/roles dedupes to one op.
    merged: dict[str, dict] = {}
    # stmt -> (env_index, plan order): first-seen global order. plan orders across roles
    # by dependency within an env; across envs we keep manifest order.
    order_key: dict[str, tuple[int, int]] = {}
    unsafe_notes: dict[str, str] = {}  # object -> reason (recreate-only changes)

    with tempfile.TemporaryDirectory() as tmp:
        manifest_hcl = os.path.join(tmp, "manifest.hcl")
        write_manifest_hcl(manifest, manifest_hcl)
        for env_idx, (env, roles_in_env) in enumerate(env_roles.items()):
            dump_dir = os.path.join(tmp, f"dump-{env}")
            write_dump(env, roles_in_env, args.ref, dump_dir)
            data = json.loads(
                run(
                    [
                        HCLEXP,
                        "plan",
                        "-manifest",
                        manifest_hcl,
                        "-env",
                        env,
                        "-dump",
                        dump_dir,
                        "-layer-root",
                        HCL_REL,
                        "-format",
                        "json",
                    ]
                )
            )
            for op in data.get("operations") or []:
                sql = op["sql"]
                entry = merged.setdefault(sql, {"op": op, "roles": set(), "envs": set()})
                entry["roles"].update(op.get("roles") or [])
                entry["envs"].add(env)
                order_key.setdefault(sql, (env_idx, op["order"]))
                if op.get("unsafe"):
                    unsafe_notes.setdefault(op["object"], op.get("unsafe_reason") or "recreate required")

    if not merged:
        raise SystemExit("No DDL generated — the HCL has no changes vs the goldens.")

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
        m = re.match(r"(\d+)", last)
        if not m:
            raise SystemExit(f"ERROR: can't parse a migration number from max_migration.txt: {last!r}")
        num = int(m.group(1)) + 1
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
