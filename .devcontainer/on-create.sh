#!/bin/bash
set -euo pipefail

# on-create.sh — Runs during prebuild (cached in snapshot).
# Heavy operations go here: dependency install, docker image pull, GeoIP DB.

echo "=== PostHog devbox: on-create (prebuild phase) ==="
cd /workspaces/posthog

# Host aliases for services that expect non-localhost hostnames
echo "127.0.0.1 kafka clickhouse objectstorage" | sudo tee -a /etc/hosts

# Python dependencies
echo "Installing Python dependencies..."
uv sync

# Node dependencies
echo "Installing Node dependencies..."
export COREPACK_ENABLE_AUTO_PIN=0
corepack enable
pnpm install --frozen-lockfile

# Pull core infrastructure + codespace service images. Profile-specific
# images (temporal, observability, dev_tools) are pulled on-demand by
# post-create.sh when the intent system starts the requested services.
echo "Pulling core Docker images..."
docker compose -f docker-compose.dev.yml -f docker-compose.codespace.yml pull --quiet || echo "Some images failed to pull (non-fatal)"

# Download GeoIP database
echo "Downloading GeoIP database..."
./bin/download-mmdb || true

echo "=== Prebuild phase complete ==="
