#!/usr/bin/env bash
# Convergence gate, step 2 of 2: diff the live HCL dumps produced by dump-live.sh
# against the committed golden per <env>-<role>, and require nothing but ignored
# operations remain. Offline — needs only hclexp (via bin/hclexp), no cluster.
#
# For each role it runs `hclexp diff -left golden -right <dump> -format json` and
# drops the operations the gate intentionally ignores — named_collections (secret
# Kafka broker config the schema golden never models) and objects whose name
# matches an exclude.hcl glob (out-of-band-managed: real on prod but not created
# by the local migrate path). Anything left is real drift: fix the migration to
# match posthog/clickhouse/hcl/, or edit the HCL layer + rerun gen-golden.sh /
# gen-sql.sh + add the migration. See README.md.
#
# Usage: check-live.sh [dumpdir]     (dumpdir defaults to $LIVE_DUMP_DIR)
#
# Env knobs:
#   VERIFY_LIVE_WARN=1     report drift but exit 0 (informational rollout).
#   VERIFY_LIVE_ENV=<env>  golden + dump env to compare (default: local).
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"      # offline wrapper (no cluster network needed)
GOLDEN="$HCL/golden"
EXCLUDE="$HCL/exclude.hcl"
ENV="${VERIFY_LIVE_ENV:-local}"
WARN="${VERIFY_LIVE_WARN:-0}"
DUMPDIR="${1:-${LIVE_DUMP_DIR:?dump dir required (pass as arg1 or set LIVE_DUMP_DIR); run dump-live.sh first}}"

ROLES=(data ops logs ai_events aux sessions)

# Object-name globs the gate ignores, parsed from exclude.hcl (the quoted glob
# strings) — the same list dump-live.sh feeds hclexp -exclude, applied here to
# the diff so golden-only out-of-band objects don't count as drift.
GATE_IGNORE="$(grep -oE '"[^"]+"' "$EXCLUDE" 2>/dev/null | tr -d '"' | tr '\n' ' ')"

# Read `hclexp diff -format json` on stdin, print the operations that count as
# real drift (one per line), exit non-zero iff any remain. Drops named_collections
# and objects matching a gate-ignore glob — both are workarounds for hclexp diff
# lacking subset/exclude scoping (PostHog/chschema#75); remove once it lands.
filter_drift() {
  # -c (not `- <<heredoc`) so stdin stays the piped JSON; globs arrive as argv.
  python3 -c '
import sys, json, fnmatch
globs = sys.argv[1:]
ops = json.load(sys.stdin).get("operations", [])
def ignored(o):
    if o.get("object_type") == "named_collection":
        return True
    name = o.get("object", "")
    return any(fnmatch.fnmatch(name, g) for g in globs)
drift = [o for o in ops if not ignored(o)]
for o in drift:
    db = o.get("database") or ""
    obj = (db + "." + o["object"]) if db else o["object"]
    flag = " [UNSAFE]" if o.get("unsafe") else ""
    print("  " + o["kind"] + " " + o["object_type"] + " " + obj + flag)
    for line in (o.get("sql") or "").strip().splitlines():
        print("      " + line)
sys.exit(1 if drift else 0)
' "$@"
}

rc=0
for role in "${ROLES[@]}"; do
  golden="$GOLDEN/$ENV-$role.hcl"
  live="$DUMPDIR/$ENV-$role.hcl"

  if [ ! -f "$golden" ]; then
    echo "== $ENV/$role: no golden ($golden) — skipping (add it to enforce this role) =="
    continue
  fi
  if [ ! -f "$live" ]; then
    echo "FAIL: no dump for $ENV/$role ($live) — run dump-live.sh first"
    rc=1; continue
  fi

  echo "== $ENV/$role: diff golden vs live dump =="
  # shellcheck disable=SC2086  # GATE_IGNORE is a deliberately word-split glob list
  if drift="$("$HCLEXP" diff -left "$golden" -right "$live" -format json | filter_drift $GATE_IGNORE)"; then
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
