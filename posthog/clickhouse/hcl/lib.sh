# Shared manifest helpers, sourced by the hcl/*.sh scripts.
#
# manifest.hcl is the single source of truth for composition, and `hclexp` parses it —
# so the shell never rebuilds a layer stack by hand. The one thing the tool cannot
# answer is "which envs does this manifest declare" (every subcommand wants -env
# up front), so manifest_envs extracts the block labels. That is label extraction,
# not HCL parsing: `env "<name>" {` labels are single-line by construction.
# Tracked upstream as a chschema issue.
#
# Callers set $HCL (the hcl/ dir, relative to the repo root) before sourcing.

MANIFEST="${MANIFEST:-$HCL/manifest.hcl}"

# Envs declared anywhere in the manifest, in first-seen order, comments ignored.
manifest_envs() {
  grep -vE '^[[:space:]]*#' "$MANIFEST" \
    | grep -oE '^[[:space:]]*env "[^"]+"' \
    | sed -E 's/.*"(.*)"/\1/' \
    | awk '!seen[$0]++'
}

# Roles the manifest deploys in $1, in manifest order.
manifest_roles() {
  "$HCLEXP" load -manifest "$MANIFEST" -env "$1" -layer-root "$HCL" -format json 2>/dev/null \
    | jq -r '.roles[].role'
}

# The resolved layer dirs for env $1 / role $2, comma-joined for `-layer`.
# -layer-root defaults to $HCL; pass $3 to resolve against another tree (diff.sh
# resolves the committed tree unpacked under a temp dir).
manifest_stack() {
  local env="$1" role="$2" root="${3:-$HCL}" manifest="${4:-$MANIFEST}"
  "$HCLEXP" load -manifest "$manifest" -env "$env" -layer-root "$root" -format json 2>/dev/null \
    | jq -r --arg r "$role" '.roles[] | select(.role == $r) | .resolved_layers | join(",")'
}
