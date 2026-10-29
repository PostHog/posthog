#!/usr/bin/env bash
# Run the live golden-path e2e for both adapters (claude + codex).
#
# Needs an ai-gateway and a token in POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY: a `phs_`
# key, or a `phe_` dev token from `hogli gateway:token` in the posthog repo.
#
# Usage:
#   bash e2e/run-e2e.sh              # both adapters, both suites
#   bash e2e/run-e2e.sh -t "(codex)" # only the codex arm (vitest -t name filter)
# Env overrides: POSTHOG_CODE_E2E_GATEWAY_URL, POSTHOG_CODE_E2E_CLAUDE_MODEL, POSTHOG_CODE_E2E_CODEX_MODEL, E2E_DEBUG=1
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(cd "$HERE/.." && pwd)"

if [[ -z "${POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY:-}" ]]; then
  echo "Set POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY to a phs_ key or a phe_ token from 'hogli gateway:token'." >&2
  exit 1
fi

export POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY
echo "gateway: ${POSTHOG_CODE_E2E_GATEWAY_URL:-http://localhost:8080}"
cd "$AGENT_DIR"
pnpm test:e2e "$@"
