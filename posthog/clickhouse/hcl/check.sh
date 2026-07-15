#!/usr/bin/env bash
# Fidelity + reference guard for the declarative ClickHouse schema.
#
# Reads the node composition manifest (./manifest.hcl) and:
#   1. `hclexp validate -manifest -env`s every role, once per env. Cross-cluster
#      Distributed proxies resolve against their target cluster's composition, so
#      the remote's existence AND its columns are checked (not blanket-skipped).
#      `system.*` remotes are always resolvable; a short known_drift_skip covers
#      real proxy/storage drift pending a fix.
#   2. `hclexp diff`s each (env, role) stack against golden/<env>-<role>.hcl,
#      asserting zero drift.
#   3. Regenerates sql/ into a temp dir and asserts it is committed fresh.
#
# Run from the repo root. Uses ./posthog/clickhouse/hcl/bin/hclexp. Exits non-zero
# on any drift or unexpected validation error.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
GOLDEN="$HCL/golden"

# shellcheck source=posthog/clickhouse/hcl/lib.sh
. "$HCL/lib.sh"

known_drift_skip() {
  case "$1" in
    prod-us) echo "query_log_archive_old_ops" ;;
    *)       echo "" ;;
  esac
}

rc=0

# Hoisted into assignments (not `for x in $(...)`) so set -e aborts on a failed
# load instead of silently iterating zero times — see lib.sh.
envs="$(manifest_envs)"

for env in $envs; do
  echo "== $env: validate (all roles) =="
  if ! "$HCLEXP" validate -manifest "$MANIFEST" -env "$env" -layer-root "$HCL" \
       -skip-validation "$(known_drift_skip "$env")" >/dev/null; then
    echo "FAIL: validate $env"; rc=1
  fi
done

for env in $envs; do
  roles="$(manifest_roles "$env")"
  for role in $roles; do
    golden="$GOLDEN/$env-$role.hcl"
    if [ ! -f "$golden" ]; then
      echo "== $env/$role: no golden (validate only) =="
      continue
    fi

    echo "== $env/$role: diff vs golden =="
    stack="$(manifest_stack "$env" "$role")"
    err="$(mktemp)"
    out="$("$HCLEXP" diff -left "$stack" -right "$golden" 2>"$err")"
    if [ "$out" != "no differences" ]; then
      echo "FAIL: drift in $env/$role"; echo "$out"; cat "$err"; rc=1
    else
      echo "no differences"
    fi
    rm -f "$err"
  done
done

echo "== sql: freshness =="
tmp_sql="$(mktemp -d)"
bash "$HCL/gen-sql.sh" "$tmp_sql" >/dev/null
if ! diff -r "$HCL/sql" "$tmp_sql" >/dev/null 2>&1; then
  echo "FAIL: sql/ is stale — run ops/gen-sql.sh and commit"; diff -r "$HCL/sql" "$tmp_sql" | head; rc=1
else
  echo "sql up to date"
fi
rm -rf "$tmp_sql"

exit $rc
