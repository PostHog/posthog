#!/usr/bin/env bash
# Preview the migration DDL your uncommitted HCL edits would produce, per env.
#
# For each OPS environment it resolves the layer stack twice — at the committed
# state (left = reference) and at your working tree (right = desired) — and runs
#   hclexp diff -left <committed> -right <working> -sql
# so the emitted statements are the migration to go committed -> changed.
#
# This is review-time companion to check.sh (which guards layers vs golden):
# check.sh asks "does the source still reproduce the captured cluster?"; this
# asks "what does my change actually do?". Read-only — never touches a cluster,
# never applies. UNSAFE (recreate) changes are flagged by hclexp.
#
# Usage (from repo root):
#   posthog/clickhouse/hcl/ops/diff.sh                 # working tree vs HEAD, all envs
#   posthog/clickhouse/hcl/ops/diff.sh prod-us         # one env
#   posthog/clickhouse/hcl/ops/diff.sh <ref>           # working tree vs an arbitrary ref
#   posthog/clickhouse/hcl/ops/diff.sh <ref> prod-eu   # both
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
BASE="$HCL/ops/base"
PROD="$HCL/ops/prod"

# env -> layer stack (kept in sync with check.sh; portable for bash 3.2).
stack_for() {
  case "$1" in
    local)   echo "$BASE,$HCL/ops/env/local" ;;
    dev)     echo "$BASE,$HCL/ops/env/dev" ;;
    prod-us) echo "$BASE,$PROD,$HCL/ops/env/prod-us" ;;
    prod-eu) echo "$BASE,$PROD,$HCL/ops/env/prod-eu" ;;
  esac
}

REF="HEAD"
ENVS="local dev prod-us prod-eu"
for arg in "$@"; do
  case "$arg" in
    local|dev|prod-us|prod-eu) ENVS="$arg" ;;
    *) REF="$arg" ;;
  esac
done

# Short-circuit when nothing under the OPS HCL changed vs the reference.
if git diff --quiet "$REF" -- "$HCL/ops" 2>/dev/null; then
  echo "no HCL changes under $HCL/ops (vs $REF)"
  exit 0
fi

# Materialize the committed tree so the left side resolves the *reference* layers.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive "$REF" "$HCL/ops" | tar -x -C "$TMP"

rc=0
for env in $ENVS; do
  working="$(stack_for "$env")"
  # Same stack, rooted in the committed snapshot.
  committed="$(stack_for "$env" | sed "s#$HCL/ops#$TMP/$HCL/ops#g")"

  echo "=============================================================="
  echo "# $env  (committed@$REF -> working tree)"
  echo "=============================================================="
  if ! "$HCLEXP" diff -left "$committed" -right "$working" -sql; then
    echo "WARN: hclexp diff failed for $env" >&2
    rc=1
  fi
  echo
done

exit $rc
