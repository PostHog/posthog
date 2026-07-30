#!/usr/bin/env bash
# Refresh the golden for every node in the composition manifest.
#
# Golden = the resolved composition (the desired/predicted schema for that node).
# For each env it runs `hclexp load -manifest -env -out golden/`, which writes one
# golden/<env>-<role>.hcl per role deployed there. check.sh then diffs the live
# composition against the golden, so a stale golden (you edited a layer but didn't
# refresh) is caught. The dump pipeline introspects the real cluster after deploy to
# confirm it converged to the golden.
#
# Run from the repo root. Uses ./posthog/clickhouse/hcl/bin/hclexp.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"
GOLDEN="$HCL/golden"

# shellcheck source=posthog/clickhouse/hcl/lib.sh
. "$HCL/lib.sh"

# Optional filters: gen-golden.sh [env] [role] — regenerate a subset.
ENV_FILTER="${1:-}"; ROLE_FILTER="${2:-}"

# Hoisted into an assignment (not `for x in $(...)`) so set -e aborts on a failed
# load instead of silently iterating zero times — see lib.sh.
envs="$(manifest_envs)"
for env in $envs; do
  [ -n "$ENV_FILTER" ] && [ "$env" != "$ENV_FILTER" ] && continue

  roles="$(manifest_roles "$env")"
  if [ -n "$ROLE_FILTER" ]; then
    printf '%s\n' "$roles" | grep -qx "$ROLE_FILTER" || continue  # not deployed in this env
    roles="$ROLE_FILTER"
    set -- -role "$ROLE_FILTER"
  else
    set --
  fi

  # -out-name writes the per-env layout golden/<env>/<role>.hcl directly, creating
  # subdirs for us (chschema#146).
  "$HCLEXP" load -manifest "$MANIFEST" -env "$env" -layer-root "$HCL" "$@" \
    -out-name '{env}/{role}' -out "$GOLDEN" >/dev/null
  for role in $roles; do echo "wrote $GOLDEN/$env/$role.hcl"; done
done
