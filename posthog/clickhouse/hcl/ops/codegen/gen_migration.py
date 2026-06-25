#!/usr/bin/env python3
"""Generate a ClickHouse migration from an OPS declarative-HCL change.

Pipeline: run the OPS diff (committed HCL -> working tree, via ops/diff.sh) to
get the DDL `hclexp` would apply, map each statement to its node-role targeting
using topology.py, and emit a migration whose `operations` are
run_sql_with_exceptions(...) calls ready to drop into
posthog/clickhouse/migrations/.

The HCL supplies *what* (the DDL); topology.py supplies *where* (node_roles); the
engine kind in topology.py supplies sharded / is_alter_on_replicated_table.

Usage (from anywhere; paths resolve relative to this file):
  HCLEXP_BIN=../python-clickhouse-schema/hclexp \
    python posthog/clickhouse/hcl/ops/codegen/gen_migration.py --name add_demo_column
  # options: --ref <git-ref> (default HEAD), --out <path|-> (default stdout)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
DIFF_SH = os.path.join("posthog", "clickhouse", "hcl", "ops", "diff.sh")

sys.path.insert(0, HERE)
from topology import TOPOLOGY  # noqa: E402

# op keyword -> (kind, is-alter?). Longer keywords first so the regex is greedy.
_OPS = [
    ("ALTER TABLE", "ALTER", True),
    ("CREATE TABLE IF NOT EXISTS", "CREATE", False),
    ("CREATE TABLE", "CREATE", False),
    ("CREATE MATERIALIZED VIEW", "CREATE", False),
    ("CREATE OR REPLACE VIEW", "CREATE", False),
    ("CREATE VIEW", "CREATE", False),
    ("DROP TABLE IF EXISTS", "DROP", False),
    ("DROP TABLE", "DROP", False),
    ("RENAME TABLE", "RENAME", False),
]
_OP_RE = re.compile(
    r"^\s*(" + "|".join(re.escape(k) for k, _, _ in _OPS) + r")\s+`?(?:posthog\.)?`?([A-Za-z0-9_$]+)`?"
)


def run_diff(ref: str) -> str:
    env = dict(os.environ)
    return subprocess.run(
        ["bash", DIFF_SH, ref], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True
    ).stdout


def parse_statements(diff_out: str) -> tuple[list[tuple[str, str]], set[str]]:
    """Return (unique [statement, env] pairs in order) and the set of UNSAFE tables.

    Statements are accumulated until a line ends with ';' (hclexp may wrap a
    CREATE across lines). Section headers from diff.sh set the current env.
    """
    statements: list[tuple[str, str]] = []
    unsafe: set[str] = set()
    seen: set[str] = set()
    env = "?"
    buf: list[str] = []
    for line in diff_out.splitlines():
        if line.startswith("# ") and "committed@" in line:
            env = line[2:].split()[0]
            continue
        if line.startswith("==") or not line.strip():
            continue
        if line.startswith("-- UNSAFE:"):
            m = re.search(r"posthog\.([A-Za-z0-9_$]+)", line)
            if m:
                unsafe.add(m.group(1))
            continue
        if line.startswith("--"):  # "-- no changes" etc.
            continue
        buf.append(line.rstrip())
        if line.rstrip().endswith(";"):
            stmt = " ".join(buf).strip()
            buf = []
            if stmt not in seen:
                seen.add(stmt)
                statements.append((stmt, env))
    return statements, unsafe


def classify(stmt: str) -> tuple[str, str]:
    m = _OP_RE.match(stmt)
    if not m:
        raise SystemExit(f"ERROR: cannot parse op/table from statement:\n  {stmt}")
    keyword, table = m.group(1), m.group(2)
    kind = next(k for kw, k, _ in _OPS if kw == keyword)
    return kind, table


def emit_operation(stmt: str, kind: str, table: str) -> str:
    if table not in TOPOLOGY:
        raise SystemExit(
            f"ERROR: object {table!r} is not in topology.py. Add it (node_roles, "
            f"replicated, sharded) before generating — node_roles is a deliberate choice."
        )
    roles, replicated, sharded = TOPOLOGY[table]
    is_alter_repl = kind == "ALTER" and replicated
    roles_src = "[" + ", ".join(f"NodeRole.{r}" for r in roles) + "]"
    sql_lit = stmt[:-1] if stmt.endswith(";") else stmt  # the runner appends nothing; keep as-is sans ';'
    return (
        "    run_sql_with_exceptions(\n"
        f"        {sql_lit!r},\n"
        f"        node_roles={roles_src},\n"
        f"        sharded={sharded},\n"
        f"        is_alter_on_replicated_table={is_alter_repl},\n"
        "    ),"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="migration slug, e.g. add_demo_column")
    ap.add_argument("--ref", default="HEAD", help="git ref to diff the working tree against")
    ap.add_argument("--out", default="-", help="output path, or - for stdout")
    args = ap.parse_args()

    statements, unsafe = parse_statements(run_diff(args.ref))
    if not statements:
        raise SystemExit("No DDL generated — the OPS HCL has no changes vs the ref.")

    ops, warnings = [], []
    for stmt, _env in statements:
        kind, table = classify(stmt)
        if table in unsafe:
            warnings.append(f"# UNSAFE (review/recreate by hand): {kind} {table}")
        ops.append(emit_operation(stmt, kind, table))

    body = (
        '"""AUTO-GENERATED from the OPS declarative HCL by '
        "posthog/clickhouse/hcl/ops/codegen/gen_migration.py.\n"
        "Review node_roles / sharded / is_alter_on_replicated_table before committing.\n"
        '"""\n'
        "from posthog.clickhouse.client.connection import NodeRole\n"
        "from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions\n\n"
    )
    if warnings:
        body += "\n".join(warnings) + "\n\n"
    body += "operations = [\n" + "\n".join(ops) + "\n]\n"

    if args.out == "-":
        sys.stdout.write(body)
    else:
        with open(args.out, "w") as f:
            f.write(body)
        sys.stderr.write(f"wrote {args.out}\n")


if __name__ == "__main__":
    main()
