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
SQL_DIR="${1:-$HCL/sql}"  # optional override (check.sh writes to a temp dir to verify freshness)

# shellcheck source=posthog/clickhouse/hcl/lib.sh
. "$HCL/lib.sh"

mkdir -p "$SQL_DIR"
# Empty schema for the diff baseline. It must live under the repo (which bin/hclexp
# bind-mounts into the container) and be referenced by a repo-relative path — an
# absolute $TMPDIR path is not visible inside the container in CI.
EMPTY="$HCL/.empty-schema.$$.hcl"; printf 'database "posthog" {\n}\n' > "$EMPTY"
trap 'rm -f "$EMPTY"' EXIT

# Hoisted into assignments (not `for x in $(...)`) so set -e aborts on a failed
# load instead of silently iterating zero times — see lib.sh.
envs="$(manifest_envs)"
for env in $envs; do
  roles="$(manifest_roles "$env")"
  for role in $roles; do
    out="$SQL_DIR/$env-$role.sql"
    stack="$(manifest_stack "$env" "$role")"
    {
      echo "-- AUTO-GENERATED from the declarative HCL by ops/gen-sql.sh — do not edit."
      echo "-- Full CREATE schema for the $env/$role node. Apply to a fresh ClickHouse to build it."
      echo
      "$HCLEXP" diff -left "$EMPTY" -right "$stack" -sql
    } > "$out"
    echo "wrote $out ($(grep -cE '^CREATE' "$out") objects)"
  done
done
