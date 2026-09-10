#!/usr/bin/env bash
# Run the live golden-path e2e for both adapters (claude + codex).
#
# Needs a local llm-gateway (run `./bin/start` in the posthog repo) and a token.
# The suite targets the gateway's `ci` product, which accepts a personal
# API key (no OAuth), so if POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY is unset this reads the repo's
# hardcoded local dev key from ee/settings.py (override the repo with POSTHOG_REPO).
# That key must be registered in the local DB — run `python manage.py
# setup_local_api_key` in the posthog repo once if auth fails.
#
# Usage:
#   bash e2e/run-e2e.sh              # both adapters, both suites
#   bash e2e/run-e2e.sh -t "(codex)" # only the codex arm (vitest -t name filter)
# Env overrides: POSTHOG_CODE_E2E_GATEWAY_URL, POSTHOG_CODE_E2E_CLAUDE_MODEL, POSTHOG_CODE_E2E_CODEX_MODEL, E2E_DEBUG=1
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "$HERE/.." && pwd)"
POSTHOG_REPO="${POSTHOG_REPO:-$(cd "$AGENT_DIR/../../.." && pwd)/posthog}"

if [[ -z "${POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY:-}" ]]; then
  SETTINGS="$POSTHOG_REPO/ee/settings.py"
  if [[ ! -f "$SETTINGS" ]]; then
    echo "POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY unset and posthog settings not found at $SETTINGS." >&2
    echo "Set POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY, or POSTHOG_REPO to the posthog checkout." >&2
    exit 1
  fi
  # The `ci` product accepts personal API keys, so no OAuth mint needed.
  POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY="$(grep -E '^DEV_API_KEY[[:space:]]*=' "$SETTINGS" | head -1 | sed -E 's/^DEV_API_KEY[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')"
fi

if [[ -z "${POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY:-}" ]]; then
  echo "Failed to obtain an POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY (no DEV_API_KEY in ee/settings.py?)." >&2
  echo "If auth then fails, run 'python manage.py setup_local_api_key' in the posthog repo." >&2
  exit 1
fi

export POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY
echo "token: ${POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY:0:8}…  gateway: ${POSTHOG_CODE_E2E_GATEWAY_URL:-http://localhost:3308/ci}"
cd "$AGENT_DIR"
pnpm test:e2e "$@"
