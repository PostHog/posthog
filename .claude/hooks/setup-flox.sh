#!/bin/bash
# SessionStart hook: capture flox environment and write to CLAUDE_ENV_FILE
# so that all subsequent Bash commands have python, node, pytest, etc. on PATH.

# Skip on Claude web (no flox there) or if CLAUDE_ENV_FILE isn't set
if [ "$CLAUDE_CODE_REMOTE" = "true" ] || [ -z "$CLAUDE_ENV_FILE" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
VENV_DIR="$PROJECT_DIR/.flox/cache/venv"

# Step 1: Capture the flox activation environment (hook.on-activate runs,
# but [profile] scripts do NOT run in non-interactive `bash -c`).
FLOX_ENV_SNAPSHOT=$(flox activate --dir "$PROJECT_DIR" -- bash -c 'printenv' 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$FLOX_ENV_SNAPSHOT" ]; then
  echo "Warning: flox activate failed, skipping env setup" >&2
  exit 0
fi

# Step 2: Extract key env vars from flox and write them to CLAUDE_ENV_FILE.
# We capture PATH and all FLOX_* vars, plus project-specific vars from [vars].
echo "$FLOX_ENV_SNAPSHOT" | grep -E "^(PATH|FLOX_|UV_PROJECT_ENVIRONMENT|OPENSSL_|LDFLAGS|CPPFLAGS|RUST_|LIBRARY_PATH|MANPATH|DOTENV_FILE|DEBUG|POSTHOG_SKIP_MIGRATION_CHECKS|FLAGS_REDIS_URL|RUSTC_WRAPPER|SCCACHE_)=" | while IFS='=' read -r key value; do
  printf 'export %s=%q\n' "$key" "$value"
done >> "$CLAUDE_ENV_FILE"

# Step 3: The flox [profile] scripts also activate the uv venv, which adds
# the venv's bin/ to PATH. Since [profile] doesn't run in `bash -c`, we do
# this manually by prepending the venv bin dir to PATH.
if [ -d "$VENV_DIR/bin" ]; then
  echo "export PATH=\"${VENV_DIR}/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
  echo "export VIRTUAL_ENV=\"${VENV_DIR}\"" >> "$CLAUDE_ENV_FILE"
fi

exit 0
