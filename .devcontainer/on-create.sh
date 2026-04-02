#!/bin/bash
set -euo pipefail

# on-create.sh — Runs during prebuild (cached in snapshot).
# Heavy operations go here: dependency install, docker image pull, migrations.

echo "=== PostHog devbox: on-create (prebuild phase) ==="
cd /workspaces/posthog

# Generate a unique SECRET_KEY for this codespace (persisted across restarts)
if [ ! -f .devcontainer/.secret_env ]; then
    printf 'export SECRET_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" > .devcontainer/.secret_env
fi

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

echo "Installing sqlx-cli..."
cargo install sqlx-cli@0.8.3 --no-default-features --features postgres &
PID_SQLX=$!

echo "Downloading GeoIP database..."
(./bin/download-mmdb && chmod 0644 share/GeoLite2-City.mmdb 2>/dev/null || true) &
PID_GEOIP=$!

# Wait for all parallel tasks (fail if any fail)
wait $PID_UV $PID_PNPM $PID_DOCKER $PID_GEOIP $PID_SQLX || {
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

echo "Waiting for Kafka..."
timeout 120 bash -c 'until rpk cluster info --brokers kafka:9092 >/dev/null 2>&1; do sleep 2; done'

# Pre-create Kafka topics that Rust services expect (they don't auto-create).
# Mirrors sandbox-entrypoint.sh from the sandbox dev environment.
echo "Pre-creating Kafka topics..."
for topic in clickhouse_events_json exceptions_ingestion; do
    rpk topic describe "$topic" --brokers kafka:9092 >/dev/null 2>&1 \
        || rpk topic create "$topic" --brokers kafka:9092 -p 1 -r 1
done

# Restore pre-migrated schema from CI if available (much faster than running
# all migrations from scratch). Falls back to full migration if unavailable.
# See hogli db:download-schema / db:restore-schema for the same pattern.
echo "Restoring pre-migrated schema from CI..."
SCHEMA_RESTORED=0
RUN_ID=$(gh api 'repos/PostHog/posthog/actions/artifacts?name=migrated-schema&per_page=10' \
    --jq '[.artifacts[] | select(.expired == false and .size_in_bytes > 10000)] | .[0].workflow_run.id' 2>/dev/null) || true
if [ -n "$RUN_ID" ] && [ "$RUN_ID" != "null" ]; then
    if gh run download "$RUN_ID" --name migrated-schema -R PostHog/posthog -D /tmp/migrated-schema-dl 2>/dev/null; then
        gunzip -c /tmp/migrated-schema-dl/schema.sql.gz | PGPASSWORD=posthog psql -h localhost -U posthog posthog >/dev/null 2>&1 && SCHEMA_RESTORED=1
        rm -rf /tmp/migrated-schema-dl
    fi
fi
if [ "$SCHEMA_RESTORED" = "1" ]; then
    echo "Schema restored from CI, running catch-up migrations..."
else
    echo "Schema restore unavailable, running full migrations..."
fi

echo "Running migrations..."
uv run python manage.py devbox_migrate

echo "=== Prebuild phase complete ==="
