#!/usr/bin/env bash
# Convergence gate, step 2 of 2: diff the live HCL dumps produced by dump-live.sh
# against the committed golden per <env>-<role>, and require the diff to come
# back empty. Offline — needs only hclexp (via bin/hclexp), no cluster.
#
# For each role it runs `hclexp diff -left golden -right <dump> -exclude
# exclude.hcl -format json`. hclexp drops the excluded objects from both sides
# itself — named_collections by object_type, out-of-band-managed and transient
# objects by name glob — so everything the diff still reports is real drift: fix
# the migration to match posthog/clickhouse/hcl/, or edit the HCL layer + rerun
# gen-golden.sh / gen-sql.sh + add the migration. See README.md.
#
# Usage: check-live.sh [dumpdir]     (dumpdir defaults to $LIVE_DUMP_DIR)
#
# Env knobs:
#   VERIFY_LIVE_WARN=1     report drift but exit 0 (informational rollout).
#   VERIFY_LIVE_ENV=<env>  golden + dump env to compare (default: local-multi).
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"      # offline wrapper (no cluster network needed)
GOLDEN="$HCL/golden"
ENV="${VERIFY_LIVE_ENV:-local-multi}"
# The same exclude dump-live.sh introspected with, so the gate ignores exactly what
# the dump dropped.
EXCLUDE="$HCL/exclude.hcl"
[ -f "$HCL/exclude-$ENV.hcl" ] && EXCLUDE="$HCL/exclude-$ENV.hcl"
WARN="${VERIFY_LIVE_WARN:-0}"
DUMPDIR="${1:-${LIVE_DUMP_DIR:?dump dir required (pass as arg1 or set LIVE_DUMP_DIR); run dump-live.sh first}}"

# shellcheck source=posthog/clickhouse/hcl/lib.sh
. "$HCL/lib.sh"

# Hoisted into an assignment (not inline in the herestring) so set -e aborts on a
# failed load instead of silently producing zero roles — see lib.sh.
roles_lines="$(manifest_roles "$ENV")"
read -r -a ROLES <<< "${roles_lines//$'\n'/ }"

# Read `hclexp diff -format json` on stdin and report its operations one per
# line, exit non-zero iff there are any. No filtering happens here: hclexp
# already applied exclude.hcl to both sides, so every operation is drift.
report_drift() {
  # -c (not `- <<heredoc`) so stdin stays the piped JSON.
  python3 -c '
import sys, json
drift = json.load(sys.stdin).get("operations", [])
for o in drift:
    db = o.get("database") or ""
    obj = (db + "." + o["object"]) if db else o["object"]
    flag = " [UNSAFE]" if o.get("unsafe") else ""
    print("  " + o["kind"] + " " + o["object_type"] + " " + obj + flag)
    for line in (o.get("sql") or "").strip().splitlines():
        print("      " + line)
sys.exit(1 if drift else 0)
'
}

rc=0
for role in "${ROLES[@]}"; do
  golden="$GOLDEN/$ENV/$(golden_name "$role").hcl"
  live="$DUMPDIR/$ENV-$role.hcl"          # transient dump, flat name from dump-live.sh

  if [ ! -f "$golden" ]; then
    echo "== $ENV/$role: no golden ($golden) — skipping (add it to enforce this role) =="
    continue
  fi
  if [ ! -f "$live" ]; then
    echo "FAIL: no dump for $ENV/$role ($live) — run dump-live.sh first"
    rc=1; continue
  fi

  echo "== $ENV/$role: diff golden vs live dump =="
  if drift="$("$HCLEXP" diff -left "$golden" -right "$live" -exclude "$EXCLUDE" -format json | report_drift)"; then
    echo "no differences"
  else
    echo "DRIFT: $ENV/$role — migrations produced a schema that differs from the HCL golden"
    echo "$drift"
    rc=1
  fi
done

if [ "$rc" -ne 0 ] && [ "$WARN" = "1" ]; then
  echo "check-live: drift detected (warn mode — not failing). Reconcile before enforcing."
  exit 0
fi
[ "$rc" -eq 0 ] && echo "check-live: live schema matches the HCL golden for all managed roles"
exit $rc
