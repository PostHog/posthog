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

# Claude Code keeps one CLAUDE_ENV_FILE for the whole session and runs SessionStart
# again on every resume and compaction. It prepends the file to every Bash command, so
# a block appended on each start grows the file until every command fails with
# "argument list too long". Each block ends with a marker line that carries its
# manifest hash, and the hook skips the write when the last marker matches the current
# manifest. Only the last marker counts, because later exports override earlier ones:
# after a switch from manifest A to B and back to A, the B block is in effect.
# The marker goes in the same write as the exports, so a failed write leaves no marker
# and the next start tries again. The hook only appends and never rewrites the file,
# because lines in it that this hook did not write are not its to remove.
MARKER_PREFIX="# setup-flox manifest-hash: "
ENV_MARKER="${MARKER_PREFIX}${MANIFEST_HASH}"
LAST_MARKER=$(grep -F "$MARKER_PREFIX" "$CLAUDE_ENV_FILE" 2>/dev/null | tail -n 1)
if [ "$LAST_MARKER" = "$ENV_MARKER" ]; then
  exit 0
fi

# Fast path: reuse cached env if manifest hash matches. The cache is read once, so the
# hash and the exports come from the same version of the file.
if [ -f "$CACHE_FILE" ] && [ -n "$MANIFEST_HASH" ]; then
  CACHE_CONTENT=$(cat "$CACHE_FILE" 2>/dev/null)
  CACHED_HASH=$(head -n 1 <<< "$CACHE_CONTENT" | sed 's/^# manifest-hash: //')
  CACHED_ENV=$(tail -n +2 <<< "$CACHE_CONTENT")
  if [ "$CACHED_HASH" = "$MANIFEST_HASH" ] && [ -n "$CACHED_ENV" ]; then
    printf '%s\n%s\n' "$CACHED_ENV" "$ENV_MARKER" >> "$CLAUDE_ENV_FILE"
    exit 0
  fi
fi

# Slow path: capture the flox activation environment.
#
# `flox activate` can block forever: an activation that was started elsewhere and
# never finished (e.g. one left blocked on a terminal's stdin) pins the shared env
# state at "Starting", and every later activation waits on it. The hook's own
# `timeout` in .claude/settings.json caps that, so a wedged activation costs the
# session a warning instead of a startup that never completes.
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
printf '%s%s\n' "$ENV_CONTENT" "$ENV_MARKER" >> "$CLAUDE_ENV_FILE"
# Another session can read the cache while this one writes it. The rename makes the
# reader see the old file or the new one, never a partial file.
printf '# manifest-hash: %s\n%s' "$MANIFEST_HASH" "$ENV_CONTENT" > "$CACHE_FILE.$$" &&
  mv -f "$CACHE_FILE.$$" "$CACHE_FILE"

exit 0
