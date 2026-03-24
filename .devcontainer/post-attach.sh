#!/bin/bash
set -euo pipefail

# post-attach.sh — Runs every time a client attaches to the codespace.
# Ensures Docker services are running (may have stopped on idle suspension).

cd /workspaces/posthog

COMPOSE_FILES="-f docker-compose.dev.yml -f docker-compose.codespace.yml -f docker-compose.profiles.yml"
# shellcheck disable=SC2086
if ! docker compose $COMPOSE_FILES ps --status running --quiet 2>/dev/null | head -1 | grep -q .; then
    echo "Restarting Docker infrastructure..."
    uv run bin/hogli docker:services:up
    timeout 120 bash -c 'until pg_isready -h localhost -U posthog 2>/dev/null; do sleep 2; done'
fi

echo "🦔 PostHog devbox attached. Run 'hogli start' to launch dev services."
