#!/usr/bin/env bash
# Local parity helper: diff the current per-env goldens against the pinned legacy
# snapshot (.legacy/, created by bin/snapshot-legacy.sh). NOT run in CI — a
# restructure PR proves parity by showing zero content diffs in committed golden/.
# This is the convenience check while iterating locally.
#
# Env mapping: legacy "local" == new "local-multi".
set -euo pipefail

HCL=posthog/clickhouse/hcl
[ -d "$HCL/.legacy/golden" ] || { echo "run $HCL/bin/snapshot-legacy.sh first"; exit 2; }

map_env() { case "$1" in local-multi) echo local ;; *) echo "$1" ;; esac; }

rc=0
for g in "$HCL"/golden/*/*.hcl; do                       # per-env-dir goldens
  [ -e "$g" ] || continue                                # no per-env goldens yet (pre-conversion)
  env=$(basename "$(dirname "$g")"); role=$(basename "$g" .hcl)
  old="$HCL/.legacy/golden/$(map_env "$env")-$role.hcl"  # legacy flat golden
  [ -f "$old" ] || continue                              # new coverage, no parity target
  out=$("$HCL/bin/hclexp" diff -left "$old" -right "$g")
  [ "$out" = "no differences" ] || { echo "PARITY FAIL: $env/$role"; echo "$out"; rc=1; }
done
[ "$rc" -eq 0 ] && echo "compare-old: all per-env goldens match the legacy snapshot"
exit $rc
