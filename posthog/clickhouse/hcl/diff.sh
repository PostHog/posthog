#!/usr/bin/env bash
# Preview the migration DDL your uncommitted HCL edits would produce, per node.
#
# For each (env, role) in the composition manifest (./manifest.hcl) it resolves the
# layer stack twice — committed (left = reference) and working tree (right = desired) —
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

# shellcheck source=posthog/clickhouse/hcl/lib.sh
. "$HCL/lib.sh"

ALL_ROLES="$(grep -oE '^role "[^"]+"' "$MANIFEST" | sed -E 's/.*"(.*)"/\1/')"

REF="HEAD"
ROLE_FILTER=""
for arg in "$@"; do
  if printf '%s\n' "$ALL_ROLES" | grep -qx "$arg"; then ROLE_FILTER="$arg"; else REF="$arg"; fi
done

if git diff --quiet "$REF" -- "$HCL" 2>/dev/null; then
  echo "no HCL changes under $HCL (vs $REF)"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive "$REF" "$HCL" | tar -x -C "$TMP"

REF_MANIFEST="$TMP/$HCL/manifest.hcl"
if [ ! -f "$REF_MANIFEST" ]; then
  echo "FAIL: $REF has no $HCL/manifest.hcl — it predates the manifest; diff against a newer ref" >&2
  exit 1
fi

rc=0
# Hoisted into assignments (not `for x in $(...)`) so set -e aborts on a failed
# load instead of silently iterating zero times — see lib.sh.
envs="$(manifest_envs)"
for env in $envs; do
  roles="$(manifest_roles "$env")"
  for role in $roles; do
    [ -n "$ROLE_FILTER" ] && [ "$role" != "$ROLE_FILTER" ] && continue

    # The ref's own manifest resolves the committed stack: a layer added or removed
    # by this change must not be attributed to the reference side.
    committed="$(manifest_stack "$env" "$role" "$TMP/$HCL" "$REF_MANIFEST")"
    working="$(manifest_stack "$env" "$role")"
    if [ -z "$committed" ]; then
      echo "=============================================================="
      echo "# $env/$role  (new node at $REF -> working tree; see gen-sql.sh for its full schema)"
      echo "=============================================================="
      echo
      continue
    fi

    echo "=============================================================="
    echo "# $env/$role  (committed@$REF -> working tree)"
    echo "=============================================================="
    if ! "$HCLEXP" diff -left "$committed" -right "$working" -sql; then
      echo "WARN: hclexp diff failed for $env/$role" >&2
      rc=1
    fi
    echo
  done
done

exit $rc
