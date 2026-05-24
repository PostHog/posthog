#!/bin/bash
# SessionStart + CwdChanged hook: capture the flox environment for the active
# project/worktree directory and write it to CLAUDE_ENV_FILE so that all
# subsequent Bash commands have python, node, pytest, etc. on PATH.
#
# CLAUDE_ENV_FILE is available in SessionStart, Setup, CwdChanged, and FileChanged
# hooks: https://code.claude.com/docs/en/hooks
#
# Wiring this to CwdChanged (not just SessionStart) is what makes the flox env
# follow you into a new worktree mid-session, e.g. after forking a conversation.
# SessionStart only fires for startup/resume/clear/compact, never for a plain
# working-directory change, so without CwdChanged a forked worktree would keep the
# original directory's venv on PATH.

# Skip on Claude web (no flox there) or if CLAUDE_ENV_FILE isn't set
if [ "$CLAUDE_CODE_REMOTE" = "true" ] || [ -z "$CLAUDE_ENV_FILE" ]; then
  exit 0
fi

# Skip if flox isn't installed
if ! command -v flox &>/dev/null; then
  exit 0
fi

# Hooks receive a JSON payload on stdin. Read it (only when stdin isn't a TTY, so
# manual invocation doesn't block) to learn the event name and the current dir.
HOOK_INPUT=""
if [ ! -t 0 ]; then
  HOOK_INPUT="$(cat)"
fi
_json_str() {
  printf '%s' "$HOOK_INPUT" | tr -d '\n' | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p"
}
HOOK_EVENT="$(_json_str hook_event_name)"
HOOK_CWD="$(_json_str cwd)"
[ -z "$HOOK_CWD" ] && HOOK_CWD="$(pwd)"

# Walk up from a starting dir to the nearest ancestor (including itself) holding a
# flox env. This is what lets the hook resolve the worktree we actually moved into.
find_flox_dir() {
  local dir="$1"
  while [ -n "$dir" ] && [ "$dir" != "/" ]; do
    if [ -f "$dir/.flox/env/manifest.toml" ]; then
      printf '%s' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

# Resolve which directory's flox env to activate. Prefer the flox dir at or above
# the current cwd. On SessionStart fall back to CLAUDE_PROJECT_DIR (covers launching
# from outside the tree); on CwdChanged do NOT fall back, so cd-ing into a non-flox
# dir (e.g. /tmp) stays a no-op instead of re-activating the project on every cd.
PROJECT_DIR="$(find_flox_dir "$HOOK_CWD")"
if [ -z "$PROJECT_DIR" ] && [ "$HOOK_EVENT" != "CwdChanged" ]; then
  PROJECT_DIR="$(find_flox_dir "${CLAUDE_PROJECT_DIR:-}")"
fi
[ -z "$PROJECT_DIR" ] && exit 0

VENV_DIR="$PROJECT_DIR/.flox/cache/venv"
CACHE_FILE="$PROJECT_DIR/.flox/cache/claude-env-cache"
FLOX_MANIFEST="$PROJECT_DIR/.flox/env/manifest.toml"

# On CwdChanged, skip if this dir's venv is already the active one (cheap path for
# cd-ing between subdirs of the same worktree). The last VIRTUAL_ENV line in
# CLAUDE_ENV_FILE reflects what subsequent Bash calls use, regardless of this hook
# process's own environment.
if [ "$HOOK_EVENT" = "CwdChanged" ] && [ -f "$CLAUDE_ENV_FILE" ]; then
  LAST_VENV=$(grep '^export VIRTUAL_ENV=' "$CLAUDE_ENV_FILE" 2>/dev/null | tail -1 | sed 's/^export VIRTUAL_ENV=//; s/^"//; s/"$//')
  if [ "$LAST_VENV" = "$VENV_DIR" ]; then
    exit 0
  fi
fi

# Checksum the flox manifest to auto-invalidate cache on env changes
MANIFEST_HASH=""
if [ -f "$FLOX_MANIFEST" ]; then
  if command -v md5sum &>/dev/null; then
    MANIFEST_HASH=$(md5sum "$FLOX_MANIFEST" | awk '{print $1}')
  elif command -v md5 &>/dev/null; then
    MANIFEST_HASH=$(md5 -q "$FLOX_MANIFEST")
  fi
fi

# Fast path: reuse cached env if manifest hash matches
if [ -f "$CACHE_FILE" ] && [ -n "$MANIFEST_HASH" ]; then
  CACHED_HASH=$(head -1 "$CACHE_FILE" | sed 's/^# manifest-hash: //')
  if [ "$CACHED_HASH" = "$MANIFEST_HASH" ]; then
    tail -n +2 "$CACHE_FILE" >> "$CLAUDE_ENV_FILE"
    exit 0
  fi
fi

# Slow path: capture the flox activation environment
FLOX_ENV_SNAPSHOT=$(flox activate --dir "$PROJECT_DIR" -- bash -c 'printenv' 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$FLOX_ENV_SNAPSHOT" ]; then
  echo "Warning: flox activate failed, skipping env setup" >&2
  exit 0
fi

ENV_CONTENT=""
while IFS='=' read -r key value; do
  ENV_CONTENT="${ENV_CONTENT}$(printf 'export %s=%q\n' "$key" "$value")"$'\n'
done < <(echo "$FLOX_ENV_SNAPSHOT" | grep -E "^(PATH|FLOX_|UV_PROJECT_ENVIRONMENT|OPENSSL_|LDFLAGS|CPPFLAGS|RUST_|LIBRARY_PATH|MANPATH|DOTENV_FILE|DEBUG|POSTHOG_SKIP_MIGRATION_CHECKS|FLAGS_REDIS_URL|RUSTC_WRAPPER|SCCACHE_)=")

if [ -d "$VENV_DIR/bin" ]; then
  ENV_CONTENT="${ENV_CONTENT}export PATH=\"${VENV_DIR}/bin:\$PATH\""$'\n'
  ENV_CONTENT="${ENV_CONTENT}export VIRTUAL_ENV=\"${VENV_DIR}\""$'\n'
fi

mkdir -p "$(dirname "$CACHE_FILE")"
printf '%s' "$ENV_CONTENT" >> "$CLAUDE_ENV_FILE"
printf '# manifest-hash: %s\n%s' "$MANIFEST_HASH" "$ENV_CONTENT" > "$CACHE_FILE"

exit 0
