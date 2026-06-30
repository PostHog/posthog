#!/usr/bin/env bash
# Convergence gate: assert the schema the ClickHouse migrations actually produced
# on the live OPS/LOGS nodes matches the committed declarative HCL golden.
#
# Run after `manage.py migrate_clickhouse` against a booted multinode stack (see
# tools/infra-scripts/clickhouse-multinode/). For each managed role it:
#   1. introspects the role's live node DB into a temp HCL (dropping unmanaged /
#      transient objects via exclude.hcl),
#   2. diffs the committed golden/<env>-<role>.hcl against the introspected HCL,
#   3. requires "no differences".
#
# A diff means a migration drifted the live schema away from the HCL (or the HCL
# wasn't regenerated for an intended change). Either fix the migration to match
# posthog/clickhouse/hcl/, or — if the change is intended — edit the HCL layer,
# rerun gen-golden.sh / gen-sql.sh, and add the migration. See README.md.
#
# Env knobs:
#   VERIFY_LIVE_WARN=1     report drift but exit 0 (informational rollout).
#   VERIFY_LIVE_ENV=<env>  golden env to compare against (default: local).
#   HCLEXP_BIN=<path>      local hclexp binary (runs on the host); otherwise a
#                          `--network host` container is used so -host localhost
#                          reaches the stack's published ports (Linux CI).
#   <ROLE>_HOST/_PORT/_DB  override a role's connection (e.g. OPS_PORT=9300).
#   CLICKHOUSE_USER / CLICKHOUSE_PASSWORD  credentials (default: default / empty).
set -euo pipefail

HCL=posthog/clickhouse/hcl
GOLDEN="$HCL/golden"
EXCLUDE="$HCL/exclude.hcl"
ENV="${VERIFY_LIVE_ENV:-local}"
WARN="${VERIFY_LIVE_WARN:-0}"
CH_USER="${CLICKHOUSE_USER:-default}"
CH_PASSWORD="${CLICKHOUSE_PASSWORD:-}"

# Match the published ports in docker-compose.multinode-clickhouse.yml.
#   role  default-host  default-port  default-db
ROLES=(
  "ops  localhost 9300 posthog"
  "logs localhost 9500 posthog"
)

# Pin to the same chschema build as bin/hclexp; override via repo variable.
HCLEXP_IMAGE="${HCLEXP_IMAGE:-ghcr.io/posthog/chschema:sha-1871283}"

# hclexp that can reach ClickHouse on the host's published ports. Prefer a local
# binary; otherwise a container sharing the host network namespace so localhost
# resolves to the published compose ports (works on Linux CI; on macOS set
# HCLEXP_BIN to a locally built binary).
run_hclexp() {
  if [[ -n "${HCLEXP_BIN:-}" ]]; then
    "$HCLEXP_BIN" "$@"
    return
  fi
  local tmp="${TMPDIR:-/tmp}"; tmp="${tmp%/}"
  docker run --rm --network host -v "$PWD:/work" -v "$tmp:$tmp" -w /work "$HCLEXP_IMAGE" "$@"
}

rc=0
for spec in "${ROLES[@]}"; do
  read -r role dhost dport ddb <<<"$spec"
  uc="$(printf '%s' "$role" | tr '[:lower:]' '[:upper:]')"
  eval "host=\"\${${uc}_HOST:-$dhost}\""
  eval "port=\"\${${uc}_PORT:-$dport}\""
  eval "db=\"\${${uc}_DB:-$ddb}\""

  golden="$GOLDEN/$ENV-$role.hcl"
  if [ ! -f "$golden" ]; then
    echo "== $ENV/$role: no golden ($golden) — skipping (add it to enforce this role) =="
    continue
  fi

  echo "== $ENV/$role: introspect $host:$port/$db =="
  # Template X's must be trailing for portability (BSD mktemp on macOS); hclexp
  # -out does not require a .hcl extension.
  live="$(mktemp "${TMPDIR:-/tmp}/verify-live-$role.XXXXXX")"
  if ! run_hclexp introspect -host "$host" -port "$port" -database "$db" \
        -user "$CH_USER" -password "$CH_PASSWORD" \
        -node "$role" -exclude "$EXCLUDE" -out "$live"; then
    echo "FAIL: introspect $ENV/$role ($host:$port/$db)"; rc=1; rm -f "$live"; continue
  fi

  echo "== $ENV/$role: diff golden vs live =="
  out="$(run_hclexp diff -left "$golden" -right "$live" 2>&1 || true)"
  if [ "$out" != "no differences" ]; then
    echo "DRIFT: $ENV/$role — migrations produced a schema that differs from the HCL golden"
    echo "$out"
    rc=1
  else
    echo "no differences"
  fi
  rm -f "$live"
done

if [ "$rc" -ne 0 ] && [ "$WARN" = "1" ]; then
  echo "verify-live: drift detected (warn mode — not failing). Reconcile before enforcing."
  exit 0
fi
[ "$rc" -eq 0 ] && echo "verify-live: OPS/LOGS live schema matches the HCL golden"
exit $rc
