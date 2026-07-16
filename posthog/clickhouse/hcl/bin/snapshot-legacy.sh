#!/usr/bin/env bash
# Materialize the legacy composition (roles/, manifest.hcl, golden/, sql/) at the
# pinned reference into a gitignored .legacy/ for local introspection and the
# compare-old.sh parity diff. Never committed — the legacy state lives only as the
# sha in legacy-ref.txt; this reconstitutes it on demand.
#
# Usage: bin/snapshot-legacy.sh [ref]   (ref defaults to legacy-ref.txt)
set -euo pipefail

HCL=posthog/clickhouse/hcl
REF="${1:-$(cat "$HCL/legacy-ref.txt")}"

rm -rf "$HCL/.legacy" && mkdir -p "$HCL/.legacy"
git archive "$REF" -- "$HCL/roles" "$HCL/manifest.hcl" "$HCL/golden" "$HCL/sql" \
  | tar -x --strip-components=3 -C "$HCL/.legacy"
echo "$REF" > "$HCL/.legacy/ref.txt"
echo "snapshot of $REF -> $HCL/.legacy"
