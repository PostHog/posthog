#!/usr/bin/env bash
# Fidelity + reference guard for the declarative ClickHouse schema.
#
# Reads the node composition manifest (./nodes) and:
#   1. `hclexp validate`s every role, once per env, via an HCL manifest rendered
#      from ./nodes + ./clusters (`-manifest`/`-env`). Cross-cluster Distributed
#      proxies resolve against their target cluster's composition, so the remote's
#      existence AND its columns are checked (not blanket-skipped). `system.*`
#      remotes are always resolvable; a short known_drift_skip covers real
#      proxy/storage drift pending a fix.
#   2. `hclexp diff`s each (env, role) stack against golden/<env>-<role>.hcl,
#      asserting zero drift.
#
# Run from the repo root. Uses ./posthog/clickhouse/hcl/bin/hclexp. Exits non-zero
# on any drift or unexpected validation error.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
GOLDEN="$HCL/golden"
MANIFEST="$HCL/nodes"
CLUSTERS="$HCL/clusters"

# Objects cross-cluster validation flags that we intentionally skip — NOT
# resolution gaps (those resolve via ./clusters). Keyed by env (validate runs per
# env). Keep shrinking; each entry needs a note explaining why it's here.
#   query_log_archive_old_ops (prod-us): legacy proxy into ops.query_log_archive_old,
#       a retired table already gone from the live prod-us cluster (per the
#       PostHog/clickhouse-schema dump) and intentionally unmanaged on ops (see
#       roles/ops/prod-eu/ops.hcl). The dead proxy still exists on the live node so
#       it stays in the golden; skip until ops drops it from the cluster.
known_drift_skip() {
  case "$1" in
    prod-us) echo "query_log_archive_old_ops" ;;
    *)       echo "" ;;
  esac
}

# csv_items CSV -> the comma list as space-separated words (no spaces in values).
csv_items() { printf '%s' "$1" | tr ',' ' '; }

# emit_hcl_list CSV -> the values as an HCL string list body: "a", "b", "c".
emit_hcl_list() {
  local first=1 x
  for x in $(csv_items "$1"); do
    [ "$first" = 1 ] && first=0 || printf ', '
    printf '"%s"' "$x"
  done
}

# render_manifest FILE -> the HCL manifest `hclexp validate -manifest` consumes:
# a role block per role (env -> layer stack, from ./nodes) plus a cluster block per
# ./clusters cluster (roles it unions + its aliases). Env-independent — `validate
# -env` selects each role's stack, and a cluster whose roles don't compose in the
# selected env resolves @absent on its own (chschema #127). `nodes` stays the
# single source of composition truth; nothing is duplicated in git.
render_manifest() {
  local out="$1" cname roles aliases
  awk '
    !/^#/ && NF>=3 {
      role=$2; env=$1; layers="";
      for (i=3;i<=NF;i++) layers = layers (layers==""?"":", ") "\"" $i "\"";
      body[role] = body[role] "  env \"" env "\" { layers = [" layers "] }\n";
      if (!(role in seen)) { order[++n]=role; seen[role]=1 }
    }
    END { for (i=1;i<=n;i++) printf "role \"%s\" {\n%s}\n", order[i], body[order[i]] }
  ' "$MANIFEST" > "$out"
  while read -r cname roles aliases; do
    [ -n "${cname:-}" ] || continue
    { printf 'cluster "%s" {\n  roles = [' "$cname"; emit_hcl_list "$roles"; printf ']\n'
      [ -n "${aliases:-}" ] && { printf '  aliases = ['; emit_hcl_list "$aliases"; printf ']\n'; }
      printf '}\n'
    } >> "$out"
  done < <(grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$CLUSTERS")
}

rc=0
# Write the rendered manifest UNDER the repo dir, not $TMPDIR: bin/hclexp runs
# hclexp in a container that bind-mounts only $PWD (-> /work), so a /tmp path is
# invisible inside it. A repo-relative path resolves under -w /work like the
# golden/layer paths do. chmod it world-readable: the chschema image runs as
# `nonroot`, but mktemp creates 0600, so the container user couldn't read it.
manifest_hcl="$(mktemp "$HCL/.hcl-manifest.XXXXXX")"
trap 'rm -f "$manifest_hcl"' EXIT
render_manifest "$manifest_hcl"
chmod 644 "$manifest_hcl"

# 1. Cross-cluster reference + column validation, once per env (validates every
#    role that composes in that env via the manifest). Cross-cluster proxies
#    resolve against ./clusters; a cluster not composed in the env resolves @absent.
for env in $(awk '!/^#/ && NF>=3 {print $1}' "$MANIFEST" | awk '!seen[$0]++'); do
  echo "== $env: validate (all roles) =="
  if ! "$HCLEXP" validate -manifest "$manifest_hcl" -env "$env" -layer-root "$HCL" \
       -skip-validation "$(known_drift_skip "$env")" >/dev/null; then
    echo "FAIL: validate $env"; rc=1
  fi
done

# 2. Golden drift, per (env, role): the committed golden is the resolved
#    composition; this catches a layer edited without regenerating.
while read -r env role layers; do
  [ -z "${env:-}" ] && continue
  case "$env" in \#*) continue ;; esac

  stack=""
  for l in $layers; do stack="${stack:+$stack,}$HCL/$l"; done

  golden="$GOLDEN/$env-$role.hcl"
  if [ -f "$golden" ]; then
    echo "== $env/$role: diff vs golden =="
    err="$(mktemp)"
    out="$("$HCLEXP" diff -left "$stack" -right "$golden" 2>"$err")"
    if [ "$out" != "no differences" ]; then
      echo "FAIL: drift in $env/$role"; echo "$out"; cat "$err"; rc=1
    else
      echo "no differences"
    fi
    rm -f "$err"
  else
    echo "== $env/$role: no golden (validate only) =="
  fi
done < "$MANIFEST"

# The committed build-from-scratch SQL (sql/<env>-<role>.sql) must match the HCL.
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
