#!/bin/bash

# Postinstall script for the Electron app
# Rebuilds native modules against Electron's Node headers and applies patches

set -e

REPO_ROOT="$(cd ../.. && pwd)"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

# CI jobs that never run Electron set this to skip ~60s of node-gyp per install.
if [ "$SKIP_ELECTRON_REBUILD" = "1" ] || [ "$SKIP_ELECTRON_REBUILD" = "true" ]; then
  echo "SKIP_ELECTRON_REBUILD=$SKIP_ELECTRON_REBUILD: skipping Electron binary check and native rebuild."
else
  # Self-heal missing Electron binary.
  # pnpm skips package-level postinstall scripts when the lockfile is already
  # satisfied, so if node_modules/electron/dist gets wiped (interrupted download,
  # cache eviction, arch change, manual cleanup), `pnpm install` won't notice —
  # and `electron-vite dev` then fails with "Electron failed to install
  # correctly, please delete node_modules/electron and try installing again".
  # Detect the missing binary and invoke Electron's own install script to fetch it.
  ELECTRON_DIST="$REPO_ROOT/node_modules/electron/dist"
  if [ ! -d "$ELECTRON_DIST" ] || [ -z "$(ls -A "$ELECTRON_DIST" 2>/dev/null)" ]; then
    echo "Electron binary missing at $ELECTRON_DIST — downloading..."
    node "$REPO_ROOT/node_modules/electron/install.js"
  fi

  echo "Rebuilding native modules for Electron..."

  cd "$REPO_ROOT"
  node scripts/rebuild-better-sqlite3-electron.mjs
fi

# Restore the execute bit on node-pty's spawn-helper. pnpm extracts node-pty's
# prebuilt binaries without preserving the executable mode, so the helper lands
# without +x and posix_spawnp fails at runtime with "posix_spawnp failed" the
# first time a terminal session is opened. Re-mark every prebuilt helper executable.
for helper in "$REPO_ROOT"/node_modules/node-pty/prebuilds/*/spawn-helper; do
  if [ -f "$helper" ] && [ ! -x "$helper" ]; then
    echo "Restoring execute bit on $helper"
    chmod +x "$helper"
  fi
done

echo "Patching Electron app name..."
bash "$SCRIPTS_DIR/patch-electron-name.sh"

echo "Downloading binaries..."
node "$SCRIPTS_DIR/download-binaries.mjs"

echo "Postinstall complete."
