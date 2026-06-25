#!/usr/bin/env python3
"""Generate a ClickHouse migration from an OPS declarative-HCL change.

Placement comes from **composition**, not a side-table: for every (env, role) node
in the manifest (`../nodes`) this diffs the committed layer stack against the working
tree and collects the DDL `hclexp` would apply. Each statement's targeting is then
derived:

  node_roles                    = the roles whose composition surfaced the statement
                                  (shared objects -> every role; OPS-only -> [OPS])
  is_alter_on_replicated_table  = ALTER on a Replicated* MergeTree (from the engine)
  sharded                       = replicated AND on the multi-shard DATA cluster
  env-specific statements       = flagged for settings.CLOUD_DEPLOYMENT gating

Output is the `operations = [...]` body for a numbered migration.

Usage (from the repo root):
  HCLEXP_BIN=../python-clickhouse-schema/hclexp \
    python posthog/clickhouse/hcl/ops/codegen/gen_migration.py --name add_foo
  # --ref <git-ref> (default HEAD), --out <path|-> (default stdout)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OPS_DIR = os.path.dirname(HERE)  # .../hcl/ops
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
OPS_REL = os.path.relpath(OPS_DIR, REPO_ROOT)  # posthog/clickhouse/hcl/ops
MANIFEST = os.path.join(OPS_DIR, "nodes")
# absolute path to the wrapper (lives at hcl/bin/hclexp); subprocess won't resolve a relative exec via cwd
HCLEXP = os.path.join(os.path.dirname(OPS_DIR), "bin", "hclexp")

# Canonical role order for emitted node_roles (mirrors ALL_ROLES in migration 0273).
# Only roles present in the manifest appear; the rest are listed for stable ordering
# if/when they are uncommented there.
ROLE_ORDER = ["data", "endpoints", "aux", "ai_events", "sessions", "logs", "ops"]

_OPS = [
    ("ALTER TABLE", "ALTER"),
    ("CREATE TABLE IF NOT EXISTS", "CREATE"),
    ("CREATE TABLE", "CREATE"),
    ("CREATE MATERIALIZED VIEW", "CREATE"),
    ("CREATE OR REPLACE VIEW", "CREATE"),
    ("CREATE VIEW", "CREATE"),
    ("DROP TABLE IF EXISTS", "DROP"),
    ("DROP TABLE", "DROP"),
    ("RENAME TABLE", "RENAME"),
]
_OP_RE = re.compile(
    r"^\s*(" + "|".join(re.escape(k) for k, _ in _OPS) + r")\s+`?(?:posthog\.)?`?([A-Za-z0-9_$]+)`?"
)


def read_manifest() -> list[tuple[str, str, list[str]]]:
    out = []
    for line in open(MANIFEST):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        out.append((parts[0], parts[1], parts[2:]))
    return out


def run(cmd: list[str], **kw) -> str:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True, **kw).stdout


def stack(root: str, layers: list[str]) -> str:
    return ",".join(os.path.join(root, OPS_REL, l) for l in layers)


def engine_map(working_root: str) -> dict[str, str]:
    """table -> engine kind, from `hclexp load` of the richest composition (prod-us/ops).

    `load` logs one line per table to stderr: `... name=<t> columns=<n> engine=<e>`.
    """
    layers = next(ls for e, r, ls in read_manifest() if (e, r) == ("prod-us", "ops"))
    res = subprocess.run(
        [HCLEXP, "load", "-layer", stack(working_root, layers)],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    out = {}
    for line in res.stderr.splitlines():
        m = re.search(r"\bname=(\S+)\s+columns=\d+\s+engine=(\S+)", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def parse_diff(text: str) -> tuple[list[str], set[str]]:
    stmts, unsafe, buf = [], set(), []
    for line in text.splitlines():
        if line.startswith("-- UNSAFE:"):
            if m := re.search(r"posthog\.([A-Za-z0-9_$]+)", line):
                unsafe.add(m.group(1))
            continue
        if line.startswith("--") or not line.strip():
            continue
        buf.append(line.rstrip())
        if line.rstrip().endswith(";"):
            stmts.append(" ".join(buf).strip())
            buf = []
    return stmts, unsafe


def classify(stmt: str) -> tuple[str, str]:
    m = _OP_RE.match(stmt)
    if not m:
        raise SystemExit(f"ERROR: cannot parse op/table from:\n  {stmt}")
    kw, table = m.group(1), m.group(2)
    return next(k for w, k in _OPS if w == kw), table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--out", default="-")
    args = ap.parse_args()

    manifest = read_manifest()
    envs_for_role: dict[str, set[str]] = {}
    for env, role, _ in manifest:
        envs_for_role.setdefault(role, set()).add(env)

    with tempfile.TemporaryDirectory() as tmp:
        # Materialize the committed OPS tree so the left side resolves the reference layers.
        tar = subprocess.run(
            ["git", "archive", args.ref, OPS_REL], cwd=REPO_ROOT, capture_output=True, check=True
        ).stdout
        subprocess.run(["tar", "-x", "-C", tmp], input=tar, check=True)

        engines = engine_map(REPO_ROOT)
        # stmt -> {(env, role)} and the union of UNSAFE objects
        seen: dict[str, set[tuple[str, str]]] = {}
        unsafe_objs: set[str] = set()
        for env, role, layers in manifest:
            left = stack(tmp, layers)
            right = stack(REPO_ROOT, layers)
            diff = run([HCLEXP, "diff", "-left", left, "-right", right, "-sql"])
            stmts, unsafe = parse_diff(diff)
            unsafe_objs |= unsafe
            for s in stmts:
                seen.setdefault(s, set()).add((env, role))

    if not seen:
        raise SystemExit("No DDL generated — the OPS HCL has no changes vs the ref.")

    operations, notes = [], []
    for stmt, where in sorted(seen.items(), key=lambda kv: classify(kv[0])[1]):
        kind, table = classify(stmt)
        roles = {r for _, r in where}
        envs = {e for e, _ in where}
        node_roles = [r for r in ROLE_ORDER if r in roles]
        replicated = engines.get(table, "").startswith("replicated_")
        is_alter_repl = kind == "ALTER" and replicated
        sharded = replicated and "data" in roles
        # Env-specific if the statement is absent from some env that hosts these roles.
        full_envs = set().union(*(envs_for_role[r] for r in roles))
        gate = "" if envs >= full_envs else f"  # NOTE: only {sorted(envs)} — gate with settings.CLOUD_DEPLOYMENT"
        if table in unsafe_objs:
            notes.append(f"# UNSAFE (review/recreate by hand): {kind} {table}")
        roles_src = "[" + ", ".join(f"NodeRole.{r.upper()}" for r in node_roles) + "]"
        sql = stmt[:-1] if stmt.endswith(";") else stmt
        operations.append(
            "    run_sql_with_exceptions(\n"
            f"        {sql!r},\n"
            f"        node_roles={roles_src},{gate}\n"
            f"        sharded={sharded},\n"
            f"        is_alter_on_replicated_table={is_alter_repl},\n"
            "    ),"
        )

    body = (
        '"""AUTO-GENERATED from the OPS declarative HCL by '
        "posthog/clickhouse/hcl/ops/codegen/gen_migration.py.\n"
        "Placement (node_roles) is derived from the node composition manifest; review before committing.\n"
        '"""\n'
        "from posthog.clickhouse.client.connection import NodeRole\n"
        "from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions\n\n"
    )
    if notes:
        body += "\n".join(notes) + "\n\n"
    body += "operations = [\n" + "\n".join(operations) + "\n]\n"

    if args.out == "-":
        sys.stdout.write(body)
    else:
        open(args.out, "w").write(body)
        sys.stderr.write(f"wrote {args.out}\n")


if __name__ == "__main__":
    main()
