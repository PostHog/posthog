#!/usr/bin/env bash
# Fidelity + reference guard for the declarative OPS ClickHouse schema.
#
# Reads the node composition manifest (./nodes) and, for each (env, role):
#   1. `hclexp validate`s the composed layer stack (cross-object refs resolve),
#      skipping refs that intentionally point outside the composed set (the
#      `system` database, the main events cluster, and the OPS-only data table
#      that the shared distributed tables read from).
#   2. `hclexp diff`s the stack against golden/<env>-<role>.hcl, asserting zero drift.
#      The golden is the resolved composition (run ops/gen-golden.sh to refresh it), so
#      this catches a stale golden — a layer edited without regenerating. Reality-fidelity
#      (HCL vs the real cluster) is the post-deploy introspection's job, not this guard.
#
# Run from the repo root. Uses ./posthog/clickhouse/hcl/bin/hclexp. Exits non-zero
# on any drift or unexpected validation error.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
GOLDEN="$HCL/golden"
MANIFEST="$HCL/nodes"

# Objects whose source/target lives outside a composed set by design:
#   - custom_metrics* read the `system` database
#   - ops_query_log_archive_mv reads system.query_log
#   - events_main / events_recent are Distributed proxies to the main events cluster
#   - query_log_archive / writable_query_log_archive are Distributed over the OPS-only
#     sharded_query_log_archive, which is absent from non-OPS (shared-only) compositions
SKIP='custom_metrics,custom_metrics_backups,custom_metrics_dictionaries,custom_metrics_part_counts,custom_metrics_replication_queue,custom_metrics_server_crash,custom_metrics_table_sizes,custom_metrics_test,ops_query_log_archive_mv,events,events_main,events_recent,writable_events_recent,query_log_archive,query_log_archive_old_ops,writable_query_log_archive,person,person_distinct_id2'

rc=0
while read -r env role layers; do
  [ -z "${env:-}" ] && continue
  case "$env" in \#*) continue ;; esac

  # Build comma-separated layer dirs rooted at the ops dir.
  stack=""
  for l in $layers; do stack="${stack:+$stack,}$HCL/$l"; done

  echo "== $env/$role: validate =="
  if ! "$HCLEXP" validate -layer "$stack" -skip-validation "$SKIP" >/dev/null; then
    echo "FAIL: validate $env/$role"; rc=1
  fi

  golden="$GOLDEN/$env-$role.hcl"
  if [ -f "$golden" ]; then
    echo "== $env/$role: diff vs golden =="
    err="$(mktemp)"
    out="$("$HCLEXP" diff -left "$stack" -right "$golden" 2>"$err")"
    if [ "$out" != "no differences" ]; then
      echo "FAIL: drift in $env/$role"; echo "$out"; cat "$err"; rc=1
    else
      echo "no differences"
    fi
    rm -f "$err"
  else
    echo "== $env/$role: no golden (validate only) =="
  fi
done < "$MANIFEST"

# The committed build-from-scratch SQL (sql/<env>-<role>.sql) must match the HCL.
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
