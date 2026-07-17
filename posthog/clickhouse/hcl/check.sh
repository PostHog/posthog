#!/usr/bin/env bash
# Fidelity + reference guard for the declarative ClickHouse schema.
#
# Reads the node composition manifest (./manifest.hcl) and:
#   1. `hclexp validate -manifest -env`s every role, once per env. Cross-cluster
#      Distributed proxies resolve against their target cluster's composition, so
#      the remote's existence AND its columns are checked (not blanket-skipped).
#      `system.*` remotes are always resolvable; a short known_drift_skip covers
#      real proxy/storage drift pending a fix.
#   2. `hclexp diff`s each (env, role) stack against golden/<env>-<role>.hcl,
#      asserting zero drift.
#   3. Regenerates sql/ into a temp dir and asserts it is committed fresh.
#
# Run from the repo root. Uses ./posthog/clickhouse/hcl/bin/hclexp. Exits non-zero
# on any drift or unexpected validation error.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
GOLDEN="$HCL/golden"

# shellcheck source=posthog/clickhouse/hcl/lib.sh
. "$HCL/lib.sh"

known_drift_skip() {
  case "$1" in
    prod-us) echo "query_log_archive_old_ops" ;;
    *)       echo "" ;;
  esac
}

rc=0

# Once-only rule (migration.md rule 4): no object may be declared in >=2 composed
# layers, except the known set parked in duplicates-baseline.txt (which only shrinks
# as Phase 2 factors objects into coshared/extend layers). We assert the current
# duplicate set equals the baseline exactly — a NEW duplicate fails (introduced
# redeclaration), and a baseline entry that is no longer duplicated also fails
# (trim it). `locate -duplicates` exits 1 whenever any duplicate exists, so we read
# its JSON rather than its exit code.
BASELINE="$HCL/duplicates-baseline.txt"
echo "== duplicates: once-only guard vs $(basename "$BASELINE") =="
# `locate -duplicates` exits 1 whenever any duplicate exists, so tolerate that here
# and judge by the parsed set, not the exit code. grep can also exit 1 (empty result
# once the baseline is emptied in Phase 4) — both must not trip set -e.
current_dups="$("$HCLEXP" locate -manifest "$MANIFEST" -layer-root "$HCL" -duplicates -format json 2>/dev/null \
  | jq -r '.duplicates[]? | "\(.database).\(.name)"' | sort -u || true)"
baseline_dups="$(grep -vE '^[[:space:]]*(#|$)' "$BASELINE" 2>/dev/null | sort -u || true)"
new_dups="$(comm -13 <(printf '%s\n' "$baseline_dups") <(printf '%s\n' "$current_dups") | grep -v '^$' || true)"
gone_dups="$(comm -23 <(printf '%s\n' "$baseline_dups") <(printf '%s\n' "$current_dups") | grep -v '^$' || true)"
if [ -n "$new_dups" ]; then
  echo "FAIL: objects declared in >=2 layers but not in the baseline — dedup them (coshared/extend), or if intentional add to $BASELINE:"
  printf '%s\n' "$new_dups" | sed 's/^/  + /'
  rc=1
fi
if [ -n "$gone_dups" ]; then
  echo "FAIL: $BASELINE lists objects no longer duplicated — remove them (the baseline only shrinks):"
  printf '%s\n' "$gone_dups" | sed 's/^/  - /'
  rc=1
fi
[ -z "$new_dups$gone_dups" ] && echo "duplicates match baseline ($(printf '%s\n' "$baseline_dups" | grep -c .) objects)"

# Hoisted into assignments (not `for x in $(...)`) so set -e aborts on a failed
# load instead of silently iterating zero times — see lib.sh.
envs="$(manifest_envs)"

for env in $envs; do
  echo "== $env: validate (all roles) =="
  if ! "$HCLEXP" validate -manifest "$MANIFEST" -env "$env" -layer-root "$HCL" \
       -skip-validation "$(known_drift_skip "$env")" >/dev/null; then
    echo "FAIL: validate $env"; rc=1
  fi
done

for env in $envs; do
  roles="$(manifest_roles "$env")"
  for role in $roles; do
    golden="$GOLDEN/$env/$role.hcl"
    if [ ! -f "$golden" ]; then
      echo "== $env/$role: no golden (validate only) =="
      continue
    fi

    echo "== $env/$role: golden freshness =="
    # Compose exactly the way gen-golden.sh does -- same command, same -out-name --
    # and require the committed file to be byte-identical to it. `hclexp diff` is
    # still run, but only to explain a failure, never to decide it: a semantic
    # compare passes a golden whose formatting has rotted away from what the
    # generator emits, which is how golden/local-multi/data.hcl kept "(is_deleted)"
    # index exprs that any regen rewrites. sql/ below has always been byte-compared;
    # golden/ now holds to the same standard.
    tmp_g="$(mktemp -d)"
    "$HCLEXP" load -manifest "$MANIFEST" -env "$env" -layer-root "$HCL" -role "$role" \
      -out-name '{env}/{role}' -out "$tmp_g" >/dev/null
    composed="$tmp_g/$env/$role.hcl"
    if ! cmp -s "$golden" "$composed"; then
      echo "FAIL: golden stale for $env/$role — run gen-golden.sh and commit"
      out="$("$HCLEXP" diff -left "$composed" -right "$golden" 2>&1 || true)"
      if [ "$out" = "no differences" ]; then
        echo "  formatting only: semantically identical, but not what gen-golden.sh emits"
      else
        echo "$out"
      fi
      rc=1
    else
      echo "golden fresh"
    fi
    rm -rf "$tmp_g"
  done
done

echo "== sql: freshness =="
tmp_sql="$(mktemp -d)"
bash "$HCL/gen-sql.sh" "$tmp_sql" >/dev/null
if ! diff -r "$HCL/sql" "$tmp_sql" >/dev/null 2>&1; then
  echo "FAIL: sql/ is stale — run ops/gen-sql.sh and commit"; diff -r "$HCL/sql" "$tmp_sql" | head; rc=1
else
  echo "sql up to date"
fi
rm -rf "$tmp_sql"

exit $rc
