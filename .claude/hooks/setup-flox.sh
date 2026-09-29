#!/bin/bash
# SessionStart hook: capture flox environment and write to CLAUDE_ENV_FILE
# so that all subsequent Bash commands have python, node, pytest, etc. on PATH.
#
# CLAUDE_ENV_FILE is only available in SessionStart hooks:
# https://code.claude.com/docs/en/hooks#sessionstart

# Skip on Claude web (no flox there) or if CLAUDE_ENV_FILE isn't set
if [ "$CLAUDE_CODE_REMOTE" = "true" ] || [ -z "$CLAUDE_ENV_FILE" ]; then
  exit 0
fi

# Skip if flox isn't installed
if ! command -v flox &>/dev/null; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
VENV_DIR="$PROJECT_DIR/.flox/cache/venv"
CACHE_FILE="$PROJECT_DIR/.flox/cache/claude-env-cache"
FLOX_MANIFEST="$PROJECT_DIR/.flox/env/manifest.toml"

# Checksum the flox manifest to auto-invalidate cache on env changes.
# On macOS md5/md5sum live in /sbin, which isn't on the PATH a SessionStart hook
# inherits. Without them MANIFEST_HASH stays empty, the fast path below is always
# skipped, and every session pays for a full `flox activate`.
PATH="$PATH:/sbin:/usr/sbin"

MANIFEST_HASH=""
if [ -f "$FLOX_MANIFEST" ]; then
  if command -v md5sum &>/dev/null; then
    MANIFEST_HASH=$(md5sum "$FLOX_MANIFEST" | awk '{print $1}')
  elif command -v md5 &>/dev/null; then
    MANIFEST_HASH=$(md5 -q "$FLOX_MANIFEST")
  elif command -v shasum &>/dev/null; then
    MANIFEST_HASH=$(shasum "$FLOX_MANIFEST" | awk '{print $1}')
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

# Slow path: capture the flox activation environment.
#
# `flox activate` can block forever: an activation that was started elsewhere and
# never finished (e.g. one left blocked on a terminal's stdin) pins the shared env
# state at "Starting", and every later activation waits on it. This hook runs at
# SessionStart, so a hang there means Claude Code never finishes starting up.
# Cap it and fall through to the no-op path instead of blocking the session.
FLOX_ACTIVATE_TIMEOUT="${FLOX_ACTIVATE_TIMEOUT:-60}"

SNAPSHOT_FILE=$(mktemp)
trap 'rm -f "$SNAPSHOT_FILE"' EXIT

flox activate --dir "$PROJECT_DIR" -- bash -c 'printenv' >"$SNAPSHOT_FILE" 2>/dev/null &
FLOX_PID=$!

# Watchdog: kill the activation (and its children, which outlive it otherwise)
# if it is still running when the budget runs out.
(
  sleep "$FLOX_ACTIVATE_TIMEOUT"
  if kill -0 "$FLOX_PID" 2>/dev/null; then
    pkill -P "$FLOX_PID" 2>/dev/null
    kill -TERM "$FLOX_PID" 2>/dev/null
    sleep 2
    pkill -9 -P "$FLOX_PID" 2>/dev/null
    kill -9 "$FLOX_PID" 2>/dev/null
  fi
) &
WATCHDOG_PID=$!

wait "$FLOX_PID" 2>/dev/null
FLOX_RC=$?

kill -TERM "$WATCHDOG_PID" 2>/dev/null
wait "$WATCHDOG_PID" 2>/dev/null

FLOX_ENV_SNAPSHOT=$(cat "$SNAPSHOT_FILE")

if [ "$FLOX_RC" -ne 0 ] || [ -z "$FLOX_ENV_SNAPSHOT" ]; then
  echo "Warning: flox activate failed or timed out after ${FLOX_ACTIVATE_TIMEOUT}s, skipping env setup" >&2
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
