#!/bin/bash
# SessionStart hook: install correct tool versions in sandbox Claude Code.
# Only runs when CLAUDE_CODE_REMOTE=true (cloud/sandbox environment).

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    exit 0
fi

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
ARCH="$(uname -m)"

# --- Parse versions from config files using Python for reliable TOML/JSON parsing ---
read -r REQUIRED_UV REQUIRED_PYTHON REQUIRED_PNPM < <(python3 -c "
import json, re, sys
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

uv_ver = python_ver = pnpm_ver = ''

# Parse pyproject.toml
if tomllib:
    try:
        with open('$PROJECT_DIR/pyproject.toml', 'rb') as f:
            data = tomllib.load(f)
        # uv required-version: strip specifier prefix (~=, >=, ==, etc.)
        raw = data.get('tool', {}).get('uv', {}).get('required-version', '')
        uv_ver = re.sub(r'^[~><=!]+', '', raw)
        # requires-python: strip specifier prefix
        raw = data.get('project', {}).get('requires-python', '')
        python_ver = re.sub(r'^[~><=!]+', '', raw)
    except Exception:
        pass

# Parse package.json
try:
    with open('$PROJECT_DIR/package.json') as f:
        pkg = json.load(f)
    pm = pkg.get('packageManager', '')
    if '@' in pm:
        pnpm_ver = pm.split('@', 1)[1]
except Exception:
    pass

print(uv_ver, python_ver, pnpm_ver)
" 2>/dev/null || echo "")

# --- 1. Upgrade uv ---
CURRENT_UV=$(uv --version 2>/dev/null | grep -oP '[0-9]+\.[0-9]+\.[0-9]+' || echo "0.0.0")

if [ -n "$REQUIRED_UV" ]; then
    # ~= means compatible release: ~=0.10.2 allows >=0.10.2, <0.11.0
    REQ_MAJOR_MINOR=$(echo "$REQUIRED_UV" | cut -d. -f1,2)
    CUR_MAJOR_MINOR=$(echo "$CURRENT_UV" | cut -d. -f1,2)
    if [ "$CUR_MAJOR_MINOR" != "$REQ_MAJOR_MINOR" ] || [ "$(printf '%s\n' "$REQUIRED_UV" "$CURRENT_UV" | sort -V | head -1)" != "$REQUIRED_UV" ]; then
        echo "Upgrading uv from $CURRENT_UV (need ~=$REQUIRED_UV)..."
        # Find latest compatible patch version from GitHub releases
        TARGET_UV=$(curl -fsSL "https://api.github.com/repos/astral-sh/uv/releases?per_page=30" 2>/dev/null \
            | grep -oP '"tag_name": "\K[0-9.]+' \
            | grep "^${REQ_MAJOR_MINOR}\." \
            | head -1)
        TARGET_UV="${TARGET_UV:-$REQUIRED_UV}"

        # Download binary directly from GitHub (uv self update doesn't work across major.minor)
        UV_BIN_DIR=$(dirname "$(command -v uv 2>/dev/null || echo "/root/.local/bin/uv")")
        case "$ARCH" in
            x86_64)  UV_ARCH="x86_64-unknown-linux-gnu" ;;
            aarch64) UV_ARCH="aarch64-unknown-linux-gnu" ;;
            *)       UV_ARCH="$ARCH-unknown-linux-gnu" ;;
        esac
        TMP_UV=$(mktemp -d)
        if curl -fsSL "https://github.com/astral-sh/uv/releases/download/${TARGET_UV}/uv-${UV_ARCH}.tar.gz" -o "$TMP_UV/uv.tar.gz" 2>/dev/null; then
            tar -xzf "$TMP_UV/uv.tar.gz" -C "$TMP_UV"
            cp "$TMP_UV/uv-${UV_ARCH}/uv" "$UV_BIN_DIR/uv"
            cp "$TMP_UV/uv-${UV_ARCH}/uvx" "$UV_BIN_DIR/uvx" 2>/dev/null || true
            echo "uv upgraded to $(uv --version 2>/dev/null)"
        else
            echo "Warning: Failed to download uv $TARGET_UV" >&2
        fi
        rm -rf "$TMP_UV"
    fi
fi

# --- 2. Install Python via uv ---
if [ -n "$REQUIRED_PYTHON" ]; then
    if ! uv python find "$REQUIRED_PYTHON" >/dev/null 2>&1; then
        echo "Installing Python $REQUIRED_PYTHON via uv..."
        uv python install "$REQUIRED_PYTHON" 2>/dev/null || true
    fi
fi

# --- 3. Install Node ---
NODE_VERSION=""
if [ -f "$PROJECT_DIR/.nvmrc" ]; then
    NODE_VERSION=$(cat "$PROJECT_DIR/.nvmrc" | tr -d '[:space:]')
    # Strip leading 'v' if present
    NODE_VERSION="${NODE_VERSION#v}"
fi

if [ -n "$NODE_VERSION" ]; then
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
    NODE_DIR="/opt/node${NODE_MAJOR}"

    CURRENT_NODE=$("$NODE_DIR/bin/node" --version 2>/dev/null | tr -d 'v' || echo "")

    if [ "$CURRENT_NODE" != "$NODE_VERSION" ]; then
        echo "Installing Node v${NODE_VERSION}..."

        # Determine arch for download
        case "$ARCH" in
            x86_64)  NODE_ARCH="x64" ;;
            aarch64) NODE_ARCH="arm64" ;;
            *)       NODE_ARCH="$ARCH" ;;
        esac

        TARBALL="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
        URL="https://nodejs.org/dist/v${NODE_VERSION}/${TARBALL}"
        TMP_DIR=$(mktemp -d)

        if wget -q -O "$TMP_DIR/$TARBALL" "$URL" 2>/dev/null || curl -fsSL -o "$TMP_DIR/$TARBALL" "$URL" 2>/dev/null; then
            rm -rf "$NODE_DIR"
            mkdir -p "$NODE_DIR"
            tar -xJf "$TMP_DIR/$TARBALL" -C "$NODE_DIR" --strip-components=1
            echo "Node v${NODE_VERSION} installed to $NODE_DIR"
        else
            echo "Warning: Failed to download Node v${NODE_VERSION}" >&2
        fi

        rm -rf "$TMP_DIR"
    fi

    # --- 4. Install pnpm via npm ---
    if [ -n "$REQUIRED_PNPM" ] && [ -x "$NODE_DIR/bin/npm" ]; then
        CURRENT_PNPM=$("$NODE_DIR/bin/pnpm" --version 2>/dev/null || echo "")
        if [ "$CURRENT_PNPM" != "$REQUIRED_PNPM" ]; then
            echo "Installing pnpm@${REQUIRED_PNPM}..."
            "$NODE_DIR/bin/npm" --prefix "$NODE_DIR" install -g "pnpm@${REQUIRED_PNPM}" 2>/dev/null || true
        fi
    fi

    # --- 5. Update PATH for this session ---
    # Prepend the new node dir so it takes precedence over older versions
    export PATH="$NODE_DIR/bin:$PATH"
fi

# Write env updates to CLAUDE_ENV_FILE if available (SessionStart only)
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    {
        [ -n "$NODE_VERSION" ] && echo "export PATH=\"/opt/node${NODE_MAJOR}/bin:\$PATH\""
    } >> "$CLAUDE_ENV_FILE"
fi

exit 0
