#!/bin/bash
# SessionStart hook: install correct tool versions in sandbox Claude Code.
# Only runs when CLAUDE_CODE_REMOTE=true (cloud/sandbox environment).

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    exit 0
fi

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
ARCH="$(uname -m)"
NODE_MAJOR=""

case "$ARCH" in
    x86_64)  UV_ARCH="x86_64-unknown-linux-gnu"; NODE_ARCH="x64" ;;
    aarch64) UV_ARCH="aarch64-unknown-linux-gnu"; NODE_ARCH="arm64" ;;
    *)       UV_ARCH="$ARCH-unknown-linux-gnu"; NODE_ARCH="$ARCH" ;;
esac

# --- Parse versions from config files using Python for reliable TOML/JSON parsing ---
# One value per line, so a missing value cannot shift the others.
REQUIRED_UV_SPEC=""
REQUIRED_PYTHON=""
REQUIRED_PNPM=""
{
    read -r REQUIRED_UV_SPEC || true
    read -r REQUIRED_PYTHON || true
    read -r REQUIRED_PNPM || true
} < <(python3 -c "
import json, re
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

uv_spec = python_ver = pnpm_ver = ''

# Parse pyproject.toml
if tomllib:
    try:
        with open('$PROJECT_DIR/pyproject.toml', 'rb') as f:
            data = tomllib.load(f)
        # Keep the comparison operator. It decides whether to track the newest uv
        # release or stay inside one major.minor series.
        uv_spec = data.get('tool', {}).get('uv', {}).get('required-version', '')
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

print(uv_spec)
print(python_ver)
print(pnpm_ver)
" 2>/dev/null || true)

# Print the uv version to install, or nothing when the current one already fits the
# spec. Version discovery reads PyPI because the egress policy blocks api.github.com.
resolve_uv_target() {
    python3 -c "
import json, re, sys, urllib.request

spec, current = sys.argv[1], sys.argv[2]
m = re.match(r'\s*([~><=!]*)\s*([0-9][0-9.]*)', spec)
if not m:
    sys.exit(0)
op, floor = (m.group(1) or '=='), m.group(2)

def parts(version):
    return tuple(int(n) for n in re.findall(r'[0-9]+', version)[:3])

def satisfies(version):
    if parts(version) < parts(floor):
        return False
    # '>=' tracks the newest release. '~=' and '==' hold one major.minor series.
    return op.startswith('>') or parts(version)[:2] == parts(floor)[:2]

if current and satisfies(current):
    sys.exit(0)

try:
    with urllib.request.urlopen('https://pypi.org/pypi/uv/json', timeout=20) as response:
        releases = json.load(response)['releases']
except Exception:
    releases = {}

best = ''
for version in releases:
    if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) and satisfies(version):
        if not best or parts(version) > parts(best):
            best = version

# Without an index, the floor is the only version known to fit the spec.
print(best or floor)
" "$1" "$2" 2>/dev/null || true
}

# Print the newest uv release on PyPI, or nothing when the index is unreachable.
latest_uv() {
    python3 -c "
import json, urllib.request
with urllib.request.urlopen('https://pypi.org/pypi/uv/json', timeout=20) as response:
    print(json.load(response)['info']['version'])
" 2>/dev/null || true
}

# Replace the uv binary in place. 'uv self update' cannot cross a major.minor boundary.
# The callers run this in an '|| true' list, which turns errexit off for the whole
# body, so each step that must succeed is checked here. Otherwise a corrupt archive
# reports the stale version as a fresh install.
install_uv() {
    local target="$1"
    local bin_dir tmp url rc=1
    bin_dir=$(dirname "$(command -v uv 2>/dev/null || echo "/root/.local/bin/uv")")
    tmp=$(mktemp -d)
    url="https://github.com/astral-sh/uv/releases/download/${target}/uv-${UV_ARCH}.tar.gz"

    if ! curl -fsSL "$url" -o "$tmp/uv.tar.gz"; then
        echo "Warning: failed to download uv $target" >&2
    elif ! tar -xzf "$tmp/uv.tar.gz" -C "$tmp"; then
        echo "Warning: failed to unpack uv $target" >&2
    elif ! cp "$tmp/uv-${UV_ARCH}/uv" "$bin_dir/uv"; then
        echo "Warning: failed to install uv $target into $bin_dir" >&2
    else
        # uvx sits beside uv in the archive, and nothing in this repo needs it.
        cp "$tmp/uv-${UV_ARCH}/uvx" "$bin_dir/uvx" 2>/dev/null || true
        echo "uv is now $(uv --version 2>/dev/null)"
        rc=0
    fi

    rm -rf "$tmp"
    return "$rc"
}

# --- 1. Upgrade uv ---
CURRENT_UV=$(uv --version 2>/dev/null | grep -oP '[0-9]+\.[0-9]+\.[0-9]+' || echo "")

if [ -n "$REQUIRED_UV_SPEC" ]; then
    TARGET_UV=$(resolve_uv_target "$REQUIRED_UV_SPEC" "$CURRENT_UV")
    if [ -n "$TARGET_UV" ]; then
        echo "Installing uv $TARGET_UV (have ${CURRENT_UV:-none}, need $REQUIRED_UV_SPEC)..."
        install_uv "$TARGET_UV" || true
    fi
fi

# --- 2. Install Python via uv ---
if [ -n "$REQUIRED_PYTHON" ]; then
    if ! uv python find "$REQUIRED_PYTHON" >/dev/null 2>&1; then
        echo "Installing Python $REQUIRED_PYTHON via uv..."
        if ! uv python install "$REQUIRED_PYTHON" 2>/dev/null; then
            # uv only installs the interpreters its own build embeds, so a Python
            # patch release newer than uv needs a newer uv first.
            LATEST_UV=$(latest_uv)
            CURRENT_UV=$(uv --version 2>/dev/null | grep -oP '[0-9]+\.[0-9]+\.[0-9]+' || echo "")
            if [ -n "$LATEST_UV" ] && [ "$LATEST_UV" != "$CURRENT_UV" ]; then
                echo "Python $REQUIRED_PYTHON is unknown to this uv, trying uv $LATEST_UV..."
                install_uv "$LATEST_UV" || true
                uv python install "$REQUIRED_PYTHON" 2>/dev/null || \
                    echo "Warning: failed to install Python $REQUIRED_PYTHON" >&2
            fi
        fi
    fi
fi

# --- 3. Install Node ---
NODE_VERSION=""
if [ -f "$PROJECT_DIR/.nvmrc" ]; then
    NODE_VERSION=$(tr -d '[:space:]' < "$PROJECT_DIR/.nvmrc")
    # Strip leading 'v' if present
    NODE_VERSION="${NODE_VERSION#v}"
fi

if [ -n "$NODE_VERSION" ]; then
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
    NODE_DIR="/opt/node${NODE_MAJOR}"

    CURRENT_NODE=$("$NODE_DIR/bin/node" --version 2>/dev/null | tr -d 'v' || echo "")

    if [ "$CURRENT_NODE" != "$NODE_VERSION" ]; then
        echo "Installing Node v${NODE_VERSION}..."

        TARBALL="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
        URL="https://nodejs.org/dist/v${NODE_VERSION}/${TARBALL}"
        TMP_DIR=$(mktemp -d)

        if wget -q -O "$TMP_DIR/$TARBALL" "$URL" || curl -fsSL -o "$TMP_DIR/$TARBALL" "$URL"; then
            rm -rf "$NODE_DIR"
            mkdir -p "$NODE_DIR"
            tar -xJf "$TMP_DIR/$TARBALL" -C "$NODE_DIR" --strip-components=1
            echo "Node v${NODE_VERSION} installed to $NODE_DIR"
        else
            echo "Warning: failed to download Node v${NODE_VERSION}" >&2
        fi

        rm -rf "$TMP_DIR"
    fi

    # --- 4. Install pnpm via npm ---
    if [ -n "$REQUIRED_PNPM" ] && [ -x "$NODE_DIR/bin/npm" ]; then
        CURRENT_PNPM=$("$NODE_DIR/bin/pnpm" --version 2>/dev/null || echo "")
        if [ "$CURRENT_PNPM" != "$REQUIRED_PNPM" ]; then
            echo "Installing pnpm@${REQUIRED_PNPM}..."
            "$NODE_DIR/bin/npm" --prefix "$NODE_DIR" install -g "pnpm@${REQUIRED_PNPM}" 2>/dev/null || \
                echo "Warning: failed to install pnpm@${REQUIRED_PNPM}" >&2
        fi
    fi

    # --- 5. Update PATH for this session ---
    # Prepend the new node dir so it takes precedence over older versions
    export PATH="$NODE_DIR/bin:$PATH"
fi

# Write env updates to CLAUDE_ENV_FILE if available (SessionStart only)
if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -n "$NODE_MAJOR" ]; then
    echo "export PATH=\"/opt/node${NODE_MAJOR}/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

exit 0
