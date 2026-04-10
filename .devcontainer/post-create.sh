#!/bin/bash
set -euo pipefail

# post-create.sh — Runs after codespace creation (not cached).
# Starts Docker services based on intent config, runs incremental migrations.

echo "=== PostHog devbox: post-create ==="
cd /workspaces/posthog

# Load generated secrets (created in on-create.sh)
# shellcheck disable=SC1091
[ -f .devcontainer/.secret_env ] && source .devcontainer/.secret_env

# Ensure interactive terminals also get the secret
grep -qF '.secret_env' ~/.bashrc 2>/dev/null || \
    echo '[ -f /workspaces/posthog/.devcontainer/.secret_env ] && source /workspaces/posthog/.devcontainer/.secret_env' >> ~/.bashrc

# Expose hogli on PATH via the venv (mirrors what flox does locally)
ln -sf /workspaces/posthog/bin/hogli /workspaces/posthog/.venv/bin/hogli

# Parse intents from Codespace secret (set by hogli box:start or manually)
INTENTS="${POSTHOG_DEVBOX_INTENTS:-product_analytics}"
echo "Intents: $INTENTS"

# Convert comma-separated intents to --with flags for hogli dev:generate
WITH_FLAGS=""
IFS=',' read -ra INTENT_ARRAY <<< "$INTENTS"
for intent in "${INTENT_ARRAY[@]}"; do
    intent=$(echo "$intent" | xargs)
    [ -n "$intent" ] && WITH_FLAGS="$WITH_FLAGS --with $intent"
done

# Generate process manager config using the intent system
echo "Generating dev environment config..."
# shellcheck disable=SC2086
uv run bin/hogli dev:generate $WITH_FLAGS

# Start Docker services (profile-aware via intent config)
echo "Starting Docker infrastructure..."
uv run bin/hogli docker:services:up

# Wait for core services (parallel)
echo "Waiting for services..."
timeout 120 bash -c 'until pg_isready -h localhost -U posthog 2>/dev/null; do sleep 2; done' &
timeout 120 bash -c 'until curl -sf http://localhost:8123/ping 2>/dev/null; do sleep 2; done' &
wait

# Run incremental migrations (instant if prebuild already migrated)
echo "Running migrations..."
uv run python manage.py devbox_migrate 2>&1 || true

# Create dev API key
uv run python manage.py setup_local_api_key 2>&1 || true

echo "=== PostHog devbox ready ==="
echo "Run 'hogli start' to launch all app processes."
