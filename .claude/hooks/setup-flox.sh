#!/bin/bash
# SessionStart hook: capture flox environment and write to CLAUDE_ENV_FILE
# so that all subsequent Bash commands have python, node, pytest, etc. on PATH.
#
# CLAUDE_ENV_FILE is only available in SessionStart hooks:
# https://code.claude.com/docs/en/hooks#sessionstart

HOOK_LOG="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/setup-flox.log"
log_hook() {
  printf '%s reason=%s remote=%q env_file=%s project=%q\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$1" \
    "${CLAUDE_CODE_REMOTE:-}" \
    "${CLAUDE_ENV_FILE:+set}" \
    "${CLAUDE_PROJECT_DIR:-}" \
    >> "$HOOK_LOG" 2>/dev/null || true
}
mark_exit() {
  log_hook "$1"
  if [ -n "$CLAUDE_ENV_FILE" ]; then
    printf 'export POSTHOG_FLOX_HOOK_EXIT=%q\n' "$1" >> "$CLAUDE_ENV_FILE"
    printf 'export POSTHOG_FLOX_HOOK_STARTED=%q\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$CLAUDE_ENV_FILE"
  fi
}
log_hook started

# Skip on Claude web (no flox there); distinguish from a missing CLAUDE_ENV_FILE
# so the log tells us which branch fired.
if [ "$CLAUDE_CODE_REMOTE" = "true" ]; then
  log_hook remote
  exit 0
fi
if [ -z "$CLAUDE_ENV_FILE" ]; then
  log_hook no_env_file
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

# Fast path: reuse cached env if manifest hash matches
if [ -f "$CACHE_FILE" ] && [ -n "$MANIFEST_HASH" ]; then
  CACHED_HASH=$(head -1 "$CACHE_FILE" | sed 's/^# manifest-hash: //')
  if [ "$CACHED_HASH" = "$MANIFEST_HASH" ]; then
    tail -n +2 "$CACHE_FILE" >> "$CLAUDE_ENV_FILE"
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

if [ -d "$VENV_DIR/bin" ]; then
  ENV_CONTENT="${ENV_CONTENT}export PATH=\"${VENV_DIR}/bin:\$PATH\""$'\n'
  ENV_CONTENT="${ENV_CONTENT}export VIRTUAL_ENV=\"${VENV_DIR}\""$'\n'
fi

mkdir -p "$(dirname "$CACHE_FILE")"
printf '%s' "$ENV_CONTENT" >> "$CLAUDE_ENV_FILE"
printf '# manifest-hash: %s\n%s' "$MANIFEST_HASH" "$ENV_CONTENT" > "$CACHE_FILE"

mark_exit fresh_snapshot
exit 0
