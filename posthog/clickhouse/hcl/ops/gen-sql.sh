#!/usr/bin/env bash
# Generate the "build-from-scratch" SQL for every node in the composition manifest.
#
# For each (env, role) it diffs the composed layer stack against an empty schema, so
# `hclexp` emits the full set of CREATE statements (dependency-ordered) that build that
# node's schema. Output: sql/<env>-<role>.sql — e.g. apply sql/local-ops.sql to a local
# ClickHouse to create the OPS schema.
#
# Run from the repo root. Uses ./posthog/clickhouse/hcl/bin/hclexp.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
OPS_DIR="$HCL/ops"
MANIFEST="$OPS_DIR/nodes"
SQL_DIR="${1:-$OPS_DIR/sql}"  # optional override (check.sh writes to a temp dir to verify freshness)

mkdir -p "$SQL_DIR"
EMPTY="$(mktemp)"; printf 'database "posthog" {\n}\n' > "$EMPTY"
trap 'rm -f "$EMPTY"' EXIT

while read -r env role layers; do
  [ -z "${env:-}" ] && continue
  case "$env" in \#*) continue ;; esac

  stack=""
  for l in $layers; do stack="${stack:+$stack,}$OPS_DIR/$l"; done

  out="$SQL_DIR/$env-$role.sql"
  {
    echo "-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit."
    echo "-- Full CREATE schema for the $env/$role node. Apply to a fresh ClickHouse to build it."
    echo
    "$HCLEXP" diff -left "$EMPTY" -right "$stack" -sql
  } > "$out"
  echo "wrote $out ($(grep -cE '^CREATE' "$out") objects)"
done < "$MANIFEST"
