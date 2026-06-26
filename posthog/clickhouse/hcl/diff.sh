#!/usr/bin/env bash
# Preview the migration DDL your uncommitted HCL edits would produce, per node.
#
# For each (env, role) in the composition manifest (./nodes) it resolves the layer
# stack twice — committed (left = reference) and working tree (right = desired) —
# and runs `hclexp diff -left <committed> -right <working> -sql`, so the emitted
# statements are the migration to go committed -> changed.
#
# Companion to check.sh (which guards composition vs golden); this asks "what does
# my change actually do?". Read-only. UNSAFE (recreate) changes are flagged by hclexp.
#
# Usage (from repo root):
#   posthog/clickhouse/hcl/diff.sh                 # working tree vs HEAD, all nodes
#   posthog/clickhouse/hcl/diff.sh <ref>           # working tree vs an arbitrary ref
#   posthog/clickhouse/hcl/diff.sh <ref> ops       # filter to one role
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
MANIFEST="$HCL/nodes"

REF="HEAD"
ROLE_FILTER=""
for arg in "$@"; do
  case "$arg" in
    ops|data|endpoints|aux|ai_events|sessions) ROLE_FILTER="$arg" ;;
    *) REF="$arg" ;;
  esac
done

if git diff --quiet "$REF" -- "$HCL" 2>/dev/null; then
  echo "no HCL changes under $HCL (vs $REF)"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive "$REF" "$HCL" | tar -x -C "$TMP"

rc=0
while read -r env role layers; do
  [ -z "${env:-}" ] && continue
  case "$env" in \#*) continue ;; esac
  [ -n "$ROLE_FILTER" ] && [ "$role" != "$ROLE_FILTER" ] && continue

  working=""; committed=""
  for l in $layers; do
    working="${working:+$working,}$HCL/$l"
    committed="${committed:+$committed,}$TMP/$HCL/$l"
  done

  echo "=============================================================="
  echo "# $env/$role  (committed@$REF -> working tree)"
  echo "=============================================================="
  if ! "$HCLEXP" diff -left "$committed" -right "$working" -sql; then
    echo "WARN: hclexp diff failed for $env/$role" >&2
    rc=1
  fi
  echo
done < "$MANIFEST"

exit $rc
