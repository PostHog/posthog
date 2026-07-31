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

rc=0; checked=0; skipped=0
for g in "$HCL"/golden/*/*.hcl; do                       # per-env-dir goldens
  [ -e "$g" ] || continue                                # no per-env goldens yet (pre-conversion)
  env=$(basename "$(dirname "$g")"); role=$(basename "$g" .hcl)
  old="$HCL/.legacy/golden/$(map_env "$env")-$role.hcl"  # legacy flat golden
  if [ ! -f "$old" ]; then                               # new coverage with no legacy counterpart
    echo "SKIP $env/$role — no legacy golden ($(basename "$old"))"; skipped=$((skipped + 1)); continue
  fi
  out=$("$HCL/bin/hclexp" diff -left "$old" -right "$g")
  if [ "$out" = "no differences" ]; then checked=$((checked + 1)); else echo "PARITY FAIL: $env/$role"; echo "$out"; rc=1; fi
done
# Report skips explicitly so a missing or mis-mapped legacy file surfaces as an
# unexpected skip rather than a silent pass.
[ "$rc" -eq 0 ] && echo "compare-old: $checked goldens match the legacy snapshot, $skipped skipped (no legacy target)"
exit $rc
