#!/bin/bash
set -euo pipefail

# post-start.sh — Runs once per codespace start (including resume from suspend).
# Ensures Docker services are running after idle suspension stops them.

cd /workspaces/posthog

# Load generated secrets (created in on-create.sh)
# shellcheck disable=SC1091
[ -f .devcontainer/.secret_env ] && source .devcontainer/.secret_env

COMPOSE_FILES="-f docker-compose.dev.yml -f docker-compose.codespace.yml -f docker-compose.profiles.yml"
# shellcheck disable=SC2086
if ! docker compose $COMPOSE_FILES ps --status running --quiet 2>/dev/null | head -1 | grep -q .; then
    echo "Restarting Docker infrastructure..."
    uv run bin/hogli docker:services:up
    timeout 120 bash -c 'until pg_isready -h localhost -U posthog 2>/dev/null; do sleep 2; done'
fi
