#!/usr/bin/env bash
# Fidelity + reference guard for the declarative OPS ClickHouse schema.
#
# For each environment it:
#   1. `hclexp validate`s the resolved layer stack (cross-object references resolve),
#      skipping references that intentionally point outside the OPS schema
#      (the `system` database and the main events cluster).
#   2. `hclexp diff`s the resolved layer stack against the vendored golden dump,
#      asserting zero drift — i.e. the layered source still reproduces the
#      last captured cluster state exactly.
#
# Run from the repo root. Uses ./posthog/clickhouse/hcl/bin/hclexp (container or
# local binary). Exits non-zero on any drift or unexpected validation error.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
BASE="$HCL/ops/base"
PROD="$HCL/ops/prod"
GOLDEN="$HCL/ops/golden"

# Objects whose source/target tables live outside the OPS schema by design:
#   - custom_metrics* views read from the `system` database
#   - ops_query_log_archive_mv reads from system.query_log
#   - events_main / events_recent are Distributed proxies to the main events cluster
SKIP='custom_metrics,custom_metrics_backups,custom_metrics_dictionaries,custom_metrics_part_counts,custom_metrics_replication_queue,custom_metrics_server_crash,custom_metrics_table_sizes,ops_query_log_archive_mv,events_main,events_recent'

# env -> layer stack (kept portable for bash 3.2; no associative arrays)
# Every environment composes the shared base layer (query_log_archive data path
# + custom_metrics views). `local` adds nothing on top; cloud envs add the
# metrics suite (prod) and per-env objects.
stack_for() {
  case "$1" in
    local)   echo "$BASE,$HCL/ops/env/local" ;;
    dev)     echo "$BASE,$HCL/ops/env/dev" ;;
    prod-us) echo "$BASE,$PROD,$HCL/ops/env/prod-us" ;;
    prod-eu) echo "$BASE,$PROD,$HCL/ops/env/prod-eu" ;;
  esac
}

# Cloud envs are diffed against a vendored golden dump captured from the live
# cluster. `local` has no external cluster dump (it is created from this HCL),
# so it is validated only — the live round-trip is exercised by the local-apply
# tooling, not this offline guard.
has_golden() { [[ "$1" != "local" ]]; }

rc=0
for env in local dev prod-us prod-eu; do
  layers="$(stack_for "$env")"

  echo "== $env: validate =="
  if ! "$HCLEXP" validate -layer "$layers" -skip-validation "$SKIP" >/dev/null; then
    echo "FAIL: validate $env"; rc=1
  fi

  if has_golden "$env"; then
    echo "== $env: diff vs golden =="
    out="$("$HCLEXP" diff -left "$layers" -right "$GOLDEN/$env-ops.hcl" 2>/dev/null)"
    if [[ "$out" != "no differences" ]]; then
      echo "FAIL: drift in $env"; echo "$out"; rc=1
    else
      echo "no differences"
    fi
  fi
done

exit $rc
