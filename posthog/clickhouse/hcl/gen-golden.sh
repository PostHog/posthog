#!/usr/bin/env bash
# Refresh the golden for every node in the composition manifest.
#
# Golden = the resolved composition (the desired/predicted schema for that node).
# For each (env, role) it runs `hclexp load -out golden/<env>-<role>.hcl`. check.sh
# then diffs the live composition against the golden, so a stale golden (you edited a
# layer but didn't refresh) is caught. The dump pipeline introspects the real cluster
# after deploy to confirm it converged to the golden.
#
# Run from the repo root. Uses ./posthog/clickhouse/hcl/bin/hclexp.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
MANIFEST="$HCL/nodes"
GOLDEN="$HCL/golden"

# Optional filters: gen-golden.sh [env] [role] — regenerate a subset.
ENV_FILTER="${1:-}"; ROLE_FILTER="${2:-}"

while read -r env role layers; do
  [ -z "${env:-}" ] && continue
  case "$env" in \#*) continue ;; esac
  [ -n "$ENV_FILTER" ] && [ "$env" != "$ENV_FILTER" ] && continue
  [ -n "$ROLE_FILTER" ] && [ "$role" != "$ROLE_FILTER" ] && continue

  stack=""
  for l in $layers; do stack="${stack:+$stack,}$HCL/$l"; done

  "$HCLEXP" load -layer "$stack" -out "$GOLDEN/$env-$role.hcl" >/dev/null 2>&1
  echo "wrote $GOLDEN/$env-$role.hcl"
done < "$MANIFEST"
