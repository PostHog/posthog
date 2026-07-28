#!/usr/bin/env bash
# Print the orchestrator contract for an external-mode bet: the events
# endpoint, the typed kinds it accepts, and a copy-paste curl skeleton.
# Foundry is passive for external bets — whatever build tooling the user
# runs is a grey box that only needs to know this contract.
#
# Usage: print-contract.sh <slug-or-id>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

if [ -z "${1:-}" ]; then
    echo "Usage: print-contract.sh <slug-or-id>" >&2
    exit 1
fi

BET_ID="$(resolve_bet_id "$1")"
URL="$(bet_url "bets/${BET_ID}/events")"

cat <<EOF
Orchestrator contract for bet ${1} (${BET_ID})
===============================================

Endpoint : POST ${URL}
Auth     : Authorization: Bearer <POSTHOG_PERSONAL_API_KEY>
Body     : {"kind": "<kind>", "payload": {...}}

Event kinds you may post (append-only — no update/delete):
  run.started, run.finished, node.spawned, node.finished, node.failed,
  artifact.ready, gate.result, exposure.started, verdict.proposed,
  budget.exceeded, knowledge.published, note

Notable transitions:
  run.started                       -> funded -> building
  gate.result {"pass": true}        -> building -> gated
  gate.result {"pass": false}       -> stays building, violations recorded
  exposure.started                  -> gated -> exposed

Curl skeleton:

  curl -X POST "${URL}" \\
    -H "Authorization: Bearer \$POSTHOG_PERSONAL_API_KEY" \\
    -H "Content-Type: application/json" \\
    --data '{"kind": "run.started", "payload": {}}'

Full payload shapes for node.*/budget.exceeded/knowledge.published are in
products/foundry/backend/presentation/serializers.py (NodeSpawnedPayloadSerializer
and friends) — malformed payloads are rejected with a field-level error.
EOF
