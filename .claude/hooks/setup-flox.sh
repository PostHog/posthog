#!/bin/bash
# SessionStart hook: capture flox environment and write to CLAUDE_ENV_FILE
# so that all subsequent Bash commands have python, node, pytest, etc. on PATH.
#
# CLAUDE_ENV_FILE is only available in SessionStart hooks:
# https://code.claude.com/docs/en/hooks#sessionstart

# Records the hook's exit path as env vars so future sessions can inspect
# what happened via `echo $POSTHOG_FLOX_HOOK_EXIT` — cheap breadcrumb for
# diagnosing failures like the cross-worktree cache pollution we hit before.
mark_exit() {
  if [ -n "$CLAUDE_ENV_FILE" ]; then
    printf 'export POSTHOG_FLOX_HOOK_EXIT=%q\n' "$1" >> "$CLAUDE_ENV_FILE"
    printf 'export POSTHOG_FLOX_HOOK_STARTED=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$CLAUDE_ENV_FILE"
  fi
}

# Skip on Claude web (no flox there); skip if CLAUDE_ENV_FILE is unset since
# we'd have nowhere to write the captured env anyway.
if [ "$CLAUDE_CODE_REMOTE" = "true" ] || [ -z "$CLAUDE_ENV_FILE" ]; then
  exit 0
fi

# Skip if flox isn't installed
if ! command -v flox &>/dev/null; then
  mark_exit no_flox
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
VENV_DIR="$PROJECT_DIR/.flox/cache/venv"
CACHE_FILE="$PROJECT_DIR/.flox/cache/claude-env-cache"
FLOX_MANIFEST="$PROJECT_DIR/.flox/env/manifest.toml"

# Checksum the flox manifest to auto-invalidate cache on env changes
MANIFEST_HASH=""
if [ -f "$FLOX_MANIFEST" ]; then
  if command -v md5sum &>/dev/null; then
    MANIFEST_HASH=$(md5sum "$FLOX_MANIFEST" | awk '{print $1}')
  elif command -v md5 &>/dev/null; then
    MANIFEST_HASH=$(md5 -q "$FLOX_MANIFEST")
  fi
fi

# Worktree-local env (VIRTUAL_ENV, PATH prepend) must NOT be cached — the
# cache file is often hardlinked across worktrees for fast setup, so caching
# these would pollute every linked worktree with one worktree's venv path.
append_worktree_local_env() {
  if [ -d "$VENV_DIR/bin" ]; then
    printf 'export PATH="%s/bin:$PATH"\n' "${VENV_DIR}" >> "$CLAUDE_ENV_FILE"
    printf 'export VIRTUAL_ENV="%s"\n' "${VENV_DIR}" >> "$CLAUDE_ENV_FILE"
  fi
}

# Fast path: reuse cached env if manifest hash matches
if [ -f "$CACHE_FILE" ] && [ -n "$MANIFEST_HASH" ]; then
  CACHED_HASH=$(head -1 "$CACHE_FILE" | sed 's/^# manifest-hash: //')
  if [ "$CACHED_HASH" = "$MANIFEST_HASH" ]; then
    tail -n +2 "$CACHE_FILE" >> "$CLAUDE_ENV_FILE"
    append_worktree_local_env
    mark_exit cache_hit
    exit 0
  fi
fi

# Slow path: capture the flox activation environment
FLOX_ENV_SNAPSHOT=$(flox activate --dir "$PROJECT_DIR" -- bash -c 'printenv' 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$FLOX_ENV_SNAPSHOT" ]; then
  echo "Warning: flox activate failed, skipping env setup" >&2
  mark_exit flox_failed
  exit 0
fi

ENV_CONTENT=""
while IFS='=' read -r key value; do
  ENV_CONTENT="${ENV_CONTENT}$(printf 'export %s=%q\n' "$key" "$value")"$'\n'
done < <(echo "$FLOX_ENV_SNAPSHOT" | grep -E "^(PATH|FLOX_|UV_PROJECT_ENVIRONMENT|OPENSSL_|LDFLAGS|CPPFLAGS|RUST_|LIBRARY_PATH|MANPATH|DOTENV_FILE|DEBUG|POSTHOG_SKIP_MIGRATION_CHECKS|FLAGS_REDIS_URL|RUSTC_WRAPPER|SCCACHE_)=")

# ENV_CONTENT deliberately excludes $VENV_DIR-based values — those are
# worktree-specific and are appended to $CLAUDE_ENV_FILE separately below so
# the cache file stays worktree-agnostic (safe to hardlink across worktrees).
mkdir -p "$(dirname "$CACHE_FILE")"
printf '%s' "$ENV_CONTENT" >> "$CLAUDE_ENV_FILE"
printf '# manifest-hash: %s\n%s' "$MANIFEST_HASH" "$ENV_CONTENT" > "$CACHE_FILE"

append_worktree_local_env

mark_exit fresh_snapshot
exit 0
