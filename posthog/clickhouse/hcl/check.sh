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

# Per-role validate skips. A Distributed table whose remote lives on another cluster
# can't be resolved from a role's own composition — skip validation for exactly those
# objects, PER ROLE, so one role never masks a proxy that should resolve locally (a
# global list would, and would grow unbounded). Each list is the minimal set `hclexp
# validate` flags for that role across all its envs; add to a role only what that role
# actually proxies cross-cluster. Building blocks:
#   _shared : out-of-band objects roles/shared models — the custom_metrics_* views and
#             ops_query_log_archive_mv, whose sources are system.* / the OPS cluster.
#   _qla    : the query_log_archive read proxies over OPS's sharded_query_log_archive.
_shared='custom_metrics_backups,custom_metrics_dictionaries,custom_metrics_part_counts,custom_metrics_replication_queue,custom_metrics_server_crash,custom_metrics_table_sizes,ops_query_log_archive_mv'
_qla='query_log_archive,writable_query_log_archive'

skip_for() {
  case "$1" in
    ops)           echo "custom_metrics,${_shared},events_main,events_recent" ;;
    logs)          echo "custom_metrics,${_shared},${_qla}" ;;
    ai_events|aux|batch_exports) echo "${_shared},${_qla}" ;;
    sessions)      echo "${_shared},${_qla},events,writable_events_recent" ;;
    sessionsv3)    echo "${_shared},${_qla},events,query_log_archive_old_ops" ;;
    # DATA is the hub: it hosts Distributed read proxies into every satellite cluster
    # (aux web/marketing preaggregated, ai_events, sessions), none of whose sharded
    # remotes live on the data node.
    data)          echo "${_shared},${_qla},ai_events,conversion_goal_attributed_preaggregated,distributed_system_processes,error_tracking_fingerprint_issue_state,experiment_metric_events_preaggregated,hog_invocation_results,marketing_conversions_preaggregated,marketing_costs_preaggregated,marketing_touchpoints_preaggregated,message_assets,property_values_distributed,session_replay_features,usage_report_events_preagg,web_bot_definition,web_bounces_dimensional_preaggregated,web_goals_preaggregated,web_overview_preaggregated,web_stats_dimensional_preaggregated,web_stats_frustration_preaggregated,web_stats_paths_preaggregated,web_stats_paths_preaggregated_pathkey,web_stats_preaggregated,web_vitals_paths_preaggregated" ;;
    *)             echo "" ;;
  esac
}

rc=0
while read -r env role layers; do
  [ -z "${env:-}" ] && continue
  case "$env" in \#*) continue ;; esac

  # Build comma-separated layer dirs rooted at the ops dir.
  stack=""
  for l in $layers; do stack="${stack:+$stack,}$HCL/$l"; done

  echo "== $env/$role: validate =="
  if ! "$HCLEXP" validate -layer "$stack" -skip-validation "$(skip_for "$role")" >/dev/null; then
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
