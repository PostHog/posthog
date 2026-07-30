# shellcheck shell=bash
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

# These helpers run inside $(...) — a plain `exit` there only kills the subshell,
# and a substitution failing in a `for` word is ignored even under set -e. Callers
# must hoist into an assignment (`roles="$(manifest_roles ...)"`) so set -e catches
# a failed load; the helpers guarantee a load failure is non-zero and on stderr,
# never an empty-but-successful result that makes the guards pass vacuously.

# Envs declared anywhere in the manifest, in first-seen order, comments ignored.
manifest_envs() {
  local envs
  envs="$(grep -vE '^[[:space:]]*#' "$MANIFEST" \
    | grep -oE '^[[:space:]]*env "[^"]+"' \
    | sed -E 's/.*"(.*)"/\1/' \
    | awk '!seen[$0]++')" || true
  [ -n "$envs" ] || { echo "ERROR: no envs declared in $MANIFEST" >&2; return 1; }
  printf '%s\n' "$envs"
}

# Roles the manifest deploys in $1, in manifest order.
manifest_roles() {
  local roles
  roles="$("$HCLEXP" load -manifest "$MANIFEST" -env "$1" -layer-root "$HCL" -format json \
    | jq -r '.roles[].role')" || true
  [ -n "$roles" ] || { echo "ERROR: no roles resolved for env $1 in $MANIFEST" >&2; return 1; }
  printf '%s\n' "$roles"
}

# The resolved layer dirs for env $1 / role $2, comma-joined for `-layer`.
# -layer-root defaults to $HCL; pass $3 to resolve against another tree (diff.sh
# resolves the committed tree unpacked under a temp dir). Empty output is legal:
# diff.sh probes a ref's manifest for roles that may not exist there yet.
manifest_stack() {
  local env="$1" role="$2" root="${3:-$HCL}" manifest="${4:-$MANIFEST}"
  "$HCLEXP" load -manifest "$manifest" -env "$env" -layer-root "$root" -format json \
    | jq -r --arg r "$role" '.roles[] | select(.role == $r) | .resolved_layers | join(",")'
}

# On-disk basename for a role's golden/sql files. Normally the role name itself, but
# `aux` is a Windows-reserved device name: git won't check out a path component named
# `aux` (core.protectNTFS) and NTFS rejects it, so its golden/sql files are written and
# read as `auxiliary` (matching the roles/auxiliary/ layer dir). The role identity —
# manifest role, NodeRole.AUX, the `aux` cluster, the hostClusterRole macro — is
# unchanged; only the generated filename differs.
golden_name() {
  case "$1" in
    aux) echo "auxiliary" ;;
    *)   echo "$1" ;;
  esac
}

# True (0) if $1's basename stem is a Windows-reserved device name (aux, con, nul,
# com1-9, lpt1-9). Those can't be a path component on Windows regardless of extension:
# git core.protectNTFS blocks the checkout and NTFS rejects the name. Committed golden/
# sql files are cross-platform, so check.sh rejects any such name — give the offending
# role a golden_name alias above.
is_reserved_basename() {
  local stem="${1##*/}"; stem="${stem%%.*}"
  case "$(printf '%s' "$stem" | tr '[:upper:]' '[:lower:]')" in
    con|prn|aux|nul|com[1-9]|lpt[1-9]) return 0 ;;
    *) return 1 ;;
  esac
}
