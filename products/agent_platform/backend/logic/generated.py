"""Loaders for TS-emitted spec vocabularies (source: services/agent-shared/src/spec/).

Don't edit *.generated.json; regenerate: UPDATE_GENERATED=1 npx vitest run src/spec/spec-codegen.test.ts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.exceptions import ImproperlyConfigured

_DIR = Path(__file__).parent


def _load(name: str) -> Any:
    # Runs at django.setup(); fail closed but legibly on a missing/corrupt artifact. Read
    # UTF-8 explicitly — the trigger-secret registry contains `→`, which a C/POSIX default decode chokes on.
    path = _DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ImproperlyConfigured(
            f"agent_platform: generated vocabulary '{name}' is missing or corrupt ({e}). "
            "Regenerate with: UPDATE_GENERATED=1 npx vitest run src/spec/spec-codegen.test.ts"
        ) from e


# Per-trigger-type required secrets (source: trigger-secrets.ts).
TRIGGER_REQUIRED_SECRETS: dict[str, list[dict[str, Any]]] = _load("trigger_required_secrets.generated.json")

# States the runner writes to `agent_tool_approval_request.state` (source: approval-store.ts).
# Consumed by the DRF serializer choices and the model's DB CheckConstraint.
APPROVAL_REQUEST_STATES: list[str] = _load("approval_request_states.generated.json")

# Assistant turn stop reasons (source: spec.ts). Consumed by the assistant-message serializer's `stopReason` choices.
ASSISTANT_STOP_REASONS: list[str] = _load("assistant_stop_reasons.generated.json")
