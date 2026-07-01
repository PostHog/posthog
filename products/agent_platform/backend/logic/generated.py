"""Loaders for TS-emitted spec vocabularies (source: services/agent-shared/src/spec/).

Don't edit *.generated.json; regenerate: UPDATE_GENERATED=1 npx vitest run src/spec/spec-codegen.test.ts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent


def _load(name: str) -> Any:
    return json.loads((_DIR / name).read_text())


# Per-trigger-type required secrets (source: trigger-secrets.ts).
TRIGGER_REQUIRED_SECRETS: dict[str, list[dict[str, Any]]] = _load("trigger_required_secrets.generated.json")

# States the runner writes to `agent_tool_approval_request.state` (source: approval-store.ts).
# Consumed by the DRF serializer choices and the model's DB CheckConstraint.
APPROVAL_REQUEST_STATES: list[str] = _load("approval_request_states.generated.json")

# Assistant turn stop reasons (source: spec.ts). Consumed by the assistant-message serializer's `stopReason` choices.
ASSISTANT_STOP_REASONS: list[str] = _load("assistant_stop_reasons.generated.json")
