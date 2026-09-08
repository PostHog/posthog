#!/usr/bin/env bash
# The two checks that need a repo other than this one.
#
#   check.sh        compose(layers) == golden/          are we self-consistent?
#   check-live.sh   golden          == a live node      does the local stack agree?
#   check-cloud.sh  compose(layers) == the cloud nodes  are we RIGHT about the cloud?
#                   + posthog-cloud-infra still composes against these layers
#
# check.sh is the merge gate and is hermetic. This one reads sibling checkouts whose
# contents change without this repo changing -- the dump repo's bot refreshes it daily
# -- so a red run here is not a build break. It is either drift to catalog or a real
# fix to make. Run it deliberately, before moving schema between the two repos.
#
# Usage, from the repo root:
#   bash posthog/clickhouse/hcl/check-cloud.sh                 # both checks, every env
#   bash posthog/clickhouse/hcl/check-cloud.sh prod-us         # just one env
#   DUMPS=/path/to/clickhouse-schema bash posthog/clickhouse/hcl/check-cloud.sh
#   CLOUD_INFRA=/path/to/posthog-cloud-infra bash posthog/clickhouse/hcl/check-cloud.sh
#
# Either half is skipped, loudly, when its checkout is absent, so this still runs
# with only one of them.
#
# Exit 1 if a composition breaks or an env drifts, so it can drive a scheduled report.
set -euo pipefail

HCL=posthog/clickhouse/hcl
HCLEXP="$HCL/bin/hclexp"

. "$HCL/lib.sh"

DUMPS="${DUMPS:-../clickhouse-schema}"
CLOUD_INFRA="${CLOUD_INFRA:-../posthog-cloud-infra}"

rc=0
envs="${*:-$(manifest_envs)}"

# ---------------------------------------------------------------------------
# 1. Reconcile: what we declare vs what the nodes actually run.
#
# Read the operations as "what you would run to make the live nodes match this
# repo". A DROP means the nodes have an object we do not declare, not that
# anything is about to be dropped -- nothing here applies DDL.
#
# .unsafe[] is a separate carrier from .operations[]: a change that needs a table
# recreated can appear there with no DDL at all, so an env can be drifting with
# zero operations. Both are counted.
# ---------------------------------------------------------------------------
if [ ! -d "$DUMPS" ]; then
  echo "== reconcile: SKIPPED, no dump repo at $DUMPS (set \$DUMPS) =="
else
  # The dump repo sits outside $PWD and $TMPDIR, so the container cannot see it
  # without an explicit mount. Absolute, because that is the path it mounts at.
  HCLEXP_MOUNT="$(cd "$DUMPS" && pwd)"
  export HCLEXP_MOUNT
  DUMPS="$HCLEXP_MOUNT"

  for env in $envs; do
    [ -d "$DUMPS/$env" ] || { echo "== $env: no dumps in $DUMPS, skipping =="; continue; }

    json="$("$HCLEXP" plan -manifest "$MANIFEST" -env "$env" -layer-root "$HCL" \
              -dump "$DUMPS/$env" -exclude "$HCL/exclude.hcl" -format json 2>/dev/null)" || {
      echo "FAIL: plan $env against $DUMPS/$env"; rc=1; continue
    }

    nops="$(printf '%s' "$json" | jq '.operations // [] | length')"
    nunsafe="$(printf '%s' "$json" | jq '.unsafe // [] | length')"
    roles="$(printf '%s' "$json" | jq -r '[.roles[].role] | join(", ")')"

    if [ "$nops" = 0 ] && [ "$nunsafe" = 0 ]; then
      echo "== $env: in sync with $DUMPS/$env ($roles) =="
      continue
    fi

    echo "== $env: $nops operation(s), $nunsafe unsafe vs $DUMPS/$env ($roles) =="
    printf '%s' "$json" | jq -r '(.operations // [])[] |
      "  \(.kind) \(.object_type) \(.database // "-").\(.object)\(if .unsafe then " [UNSAFE]" else "" end)"'
    printf '%s' "$json" | jq -r '(.unsafe // [])[] | "  !! UNSAFE \(.object): \(.reason)"'
    rc=1
  done
fi

# ---------------------------------------------------------------------------
# 2. The compose gate, locally.
#
# posthog-cloud-infra pins this repo at its base-ref and sparse-vendors layers on
# demand. CI proves it still composes by dispatching a workflow there against this
# branch; this reproduces that answer offline.
#
# Its checkout is copied to a scratch dir first and vendored there. Vendoring into
# the real one would leave a tree that does not match its base-ref, which is a
# confusing state to hand back to someone.
# ---------------------------------------------------------------------------
if [ ! -d "$CLOUD_INFRA/clickhouse/hcl" ]; then
  echo "== compose gate: SKIPPED, no posthog-cloud-infra at $CLOUD_INFRA (set \$CLOUD_INFRA) =="
else
  stage="$(mktemp -d)"
  trap 'rm -rf "$stage"' EXIT
  cp -R "$CLOUD_INFRA/clickhouse" "$stage/clickhouse"
  CI_HCL="$stage/clickhouse/hcl"
  CI_MANIFEST="$CI_HCL/manifest.hcl"
  vendor="$CI_HCL/vendor/posthog-hcl"
  rm -rf "$vendor"

  # Vendor exactly what its manifest names, the way bin/vendor-base.sh does, but
  # from the working tree instead of from base-ref: the question is whether THIS
  # tree still composes there.
  missing=""
  for path in $(grep -oE '"vendor/posthog-hcl/[^"]+"' "$CI_MANIFEST" | tr -d '"' | sort -u); do
    rel="${path#vendor/posthog-hcl/}"
    if [ ! -e "$HCL/$rel" ]; then
      missing="$missing  $rel"$'\n'
      continue
    fi
    mkdir -p "$vendor/$(dirname "$rel")"
    cp -R "$HCL/$rel" "$vendor/$rel"
  done

  if [ -n "$missing" ]; then
    echo "FAIL: posthog-cloud-infra's manifest references layers this tree does not have:"
    printf '%s' "$missing"
    echo "  Removing or renaming a vendored layer breaks its composition -- add it back, or land the rename there first."
    rc=1
  fi

  echo "== compose gate: posthog-cloud-infra vs this working tree =="
  for env in $(MANIFEST="$CI_MANIFEST" manifest_envs); do
    # -skip-validation '*' matches its own check.sh: the cross-cluster remotes it
    # cannot resolve are roles that repo does not compose, so they are skipped there
    # too. This asks the narrower question the gate asks -- does it still compose.
    if "$HCLEXP" validate -manifest "$CI_MANIFEST" -env "$env" -layer-root "$CI_HCL" \
         -skip-validation '*' >/dev/null 2>&1; then
      echo "  $env: composes"
    else
      echo "  FAIL: $env does not compose against these layers"
      "$HCLEXP" validate -manifest "$CI_MANIFEST" -env "$env" -layer-root "$CI_HCL" \
        -skip-validation '*' 2>&1 | sed 's/^/    /' | tail -20
      rc=1
    fi
  done

  # Its once-only guard reads across both repos' layers at once, so a hoist here can
  # collide with something it declares. Its baseline is the reference, not ours.
  ci_baseline="$CI_HCL/duplicates-baseline.txt"
  if [ -f "$ci_baseline" ]; then
    cur="$("$HCLEXP" locate -manifest "$CI_MANIFEST" -layer-root "$CI_HCL" -duplicates -format json 2>/dev/null \
            | jq -r '.duplicates[]? | "\(.database).\(.name)"' | sort -u || true)"
    base="$(grep -vE '^[[:space:]]*(#|$)' "$ci_baseline" | sort -u || true)"
    new="$(comm -13 <(printf '%s\n' "$base") <(printf '%s\n' "$cur") | grep -v '^$' || true)"
    if [ -n "$new" ]; then
      echo "  FAIL: these objects become duplicates in posthog-cloud-infra's composition:"
      printf '%s\n' "$new" | sed 's/^/    + /'
      rc=1
    else
      echo "  duplicates: no new entries against its baseline"
    fi
  fi
fi

exit $rc
