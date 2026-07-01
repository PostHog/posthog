#!/usr/bin/env bash
# Convergence gate, step 1 of 2: introspect the live OPS/LOGS nodes on a booted
# multinode stack (see tools/infra-scripts/clickhouse-multinode/) into one HCL
# dump per <env>-<role>. Step 2 (check-live.sh) diffs those dumps against the
# committed golden — offline. Splitting keeps the cluster/network-dependent
# capture separate from the deterministic comparison.
#
# Transient / unmanaged objects are dropped at introspect time via exclude.hcl.
#
# Usage: dump-live.sh [outdir]
#   outdir defaults to $LIVE_DUMP_DIR, else a fresh temp dir. The dir is printed
#   as the last stdout line so a caller can capture it; progress goes to stderr.
#   Keep it under $TMPDIR or the repo so the containerized hclexp can see it.
#
# Env knobs:
#   VERIFY_LIVE_ENV=<env>  names the dump files (default: local).
#   HCLEXP_BIN=<path>      local hclexp binary (host network); otherwise a
#                          `--network host` container reaches the published ports.
#   <ROLE>_HOST/_PORT/_DB  override a role's connection (e.g. OPS_PORT=9300).
#   CLICKHOUSE_USER / CLICKHOUSE_PASSWORD  credentials (default: default / empty).
set -euo pipefail

HCL=posthog/clickhouse/hcl
EXCLUDE="$HCL/exclude.hcl"
ENV="${VERIFY_LIVE_ENV:-local}"
CH_USER="${CLICKHOUSE_USER:-default}"
CH_PASSWORD="${CLICKHOUSE_PASSWORD:-}"
OUTDIR="${1:-${LIVE_DUMP_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/ch-live-dump.XXXXXX")}}"
mkdir -p "$OUTDIR"

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

  out="$OUTDIR/$ENV-$role.hcl"
  echo "== dump $ENV/$role from $host:$port/$db -> $out ==" >&2
  if ! run_hclexp introspect -host "$host" -port "$port" -database "$db" \
        -user "$CH_USER" -password "$CH_PASSWORD" \
        -node "$role" -exclude "$EXCLUDE" -out "$out"; then
    echo "FAIL: introspect $ENV/$role ($host:$port/$db)" >&2
    rc=1
  fi
done

echo "$OUTDIR"
exit $rc
