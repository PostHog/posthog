#!/usr/bin/env bash
# Download a JetBrains IDE into a host directory and trigger in-container setup.
# Called by cloud-init.sh as a background task after the sandbox is live.
#
# Usage: install-jetbrains.sh <product> <dest_dir> <branch>
#   product:  "intellij" or "pycharm"
#   dest_dir: host path to extract IDE into (bind-mounted at /opt/idea)
#   branch:   sandbox branch name (used to derive container name)
set -euo pipefail

PRODUCT="$1"
DEST_DIR="$2"
BRANCH="$3"

log() { echo "[$(date '+%H:%M:%S')] [jetbrains] $*"; }

case "$PRODUCT" in
    intellij) CODE="IIU" ;;
    pycharm)  CODE="PCP" ;;
    *)        log "Unknown product: $PRODUCT"; exit 1 ;;
esac

API="https://data.services.jetbrains.com/products/releases?code=${CODE}&latest=true&type=release"
URL=$(curl -sfL "$API" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data['${CODE}'][0]['downloads']['linux']['link'])")

log "Downloading $PRODUCT to $DEST_DIR..."
curl -fSL "$URL" | tar -xzf - -C "$DEST_DIR" --strip-components=1
log "$PRODUCT downloaded"

# Derive container name: sandbox-{slugified_branch}-app-1
SLUG=$(echo "$BRANCH" | tr '/' '-' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g')
CONTAINER="sandbox-${SLUG}-app-1"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    log "Triggering setup inside $CONTAINER..."
    docker exec -e SANDBOX_MODE=setup-jetbrains "$CONTAINER" python3 bin/sandbox-entrypoint.py || \
        log "WARNING: in-container setup failed (will retry on next container start)"
else
    log "Container $CONTAINER not running — setup will run on next start"
fi
