#!/bin/bash
set -euo pipefail

# on-create.sh — Runs during prebuild (cached in snapshot).
# Heavy operations go here: dependency install, docker image pull, migrations.

echo "=== PostHog devbox: on-create (prebuild phase) ==="
cd /workspaces/posthog

# Host aliases for services that expect non-localhost hostnames
echo "127.0.0.1 kafka clickhouse objectstorage" | sudo tee -a /etc/hosts

# --- Parallel dependency installs ---

echo "Installing Python dependencies..."
uv sync &
PID_UV=$!

echo "Installing Node dependencies..."
(
    export COREPACK_ENABLE_AUTO_PIN=0
    corepack enable
    pnpm install --frozen-lockfile
) &
PID_PNPM=$!

echo "Pulling core Docker images..."
docker compose -f docker-compose.dev.yml -f docker-compose.codespace.yml pull --quiet &
PID_DOCKER=$!

echo "Downloading GeoIP database..."
./bin/download-mmdb &
PID_GEOIP=$!

# Wait for all parallel tasks (fail if any fail)
wait $PID_UV $PID_PNPM $PID_DOCKER $PID_GEOIP || {
    echo "One or more install steps failed"
    exit 1
}

# Expose hogli on PATH via the venv (mirrors what flox does locally)
ln -sf /workspaces/posthog/bin/hogli /workspaces/posthog/.venv/bin/hogli

# --- Pre-migrate (DB state cached in prebuild snapshot) ---

echo "Starting core infrastructure for pre-migration..."
COMPOSE_FILES="-f docker-compose.dev.yml -f docker-compose.codespace.yml"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES up -d db clickhouse redis7 zookeeper kafka

echo "Waiting for PostgreSQL..."
timeout 120 bash -c 'until pg_isready -h localhost -U posthog 2>/dev/null; do sleep 2; done'

echo "Waiting for ClickHouse..."
timeout 120 bash -c 'until curl -sf http://localhost:8123/ping 2>/dev/null; do sleep 2; done'

echo "Running migrations..."
uv run python manage.py devbox_migrate

echo "=== Prebuild phase complete ==="
