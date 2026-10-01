import json

from django.utils import timezone

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.models.user import User

from products.context_layer.backend.models import ContextSelectionAttempt
from products.context_layer.backend.selection_service import selection_mode
from products.context_layer.backend.selection_sources import validate_candidates
from products.context_layer.backend.selection_types import Candidate
from products.tasks.backend.models import TaskRun


def validate_exposure(attempt: ContextSelectionAttempt, data: dict) -> None:
    prompt = json.loads(data["prompt"])
    if isinstance(prompt, list):
        last = prompt[-1] if prompt else None
        meta = last.get("_meta") if isinstance(last, dict) else None
        ui = meta.get("ui") if isinstance(meta, dict) else None
        included = (
            isinstance(last, dict)
            and last.get("type") == "text"
            and isinstance(ui, dict)
            and ui.get("hidden") is True
            and last.get("text") == attempt.context
        )
    elif isinstance(prompt, dict) and prompt.get("format") == "pi_context":
        messages = prompt.get("messages")
        last = messages[-1] if isinstance(messages, list) and messages else None
        included = (
            isinstance(last, dict)
            and last.get("role") == "custom"
            and last.get("customType") == "posthog_context_selection"
            and last.get("content") == attempt.context
        )
    else:
        raise ValidationError("Unsupported runtime prompt format.")
    if data["context_included"] != bool(attempt.context and included):
        raise ValidationError("Context exposure does not match the archived prompt.")
    if data["context_included"] and (attempt.mode != "treatment" or attempt.status != "selected"):
        raise ValidationError("This selection supplied no treatment context.")


def validate_dispatch(attempt: ContextSelectionAttempt, run: TaskRun, actor: User, scopes: set[str]) -> None:
    if selection_mode(run, actor) == "disabled":
        raise PermissionDenied("Context selection is disabled.")
    source_scope = {
        "skill": "llm_skill:read",
        "metric": "data_catalog:read",
        "certification": "data_catalog:read",
        "relationship": "data_catalog:read",
        "business_knowledge": "business_knowledge:read",
    }
    selected = set(attempt.evidence.get("selected_ids", []))
    candidates = [
        Candidate(**c) for c in attempt.evidence.get("retrieval", {}).get("candidates", []) if c["id"] in selected
    ]
    if any(source_scope[c.kind] not in scopes for c in candidates):
        raise PermissionDenied("A selected source scope is no longer available.")
    current = {c.id: c.as_json() for c in validate_candidates(run.team, actor, candidates)}
    if len(candidates) != len(selected) or any(current.get(c.id) != c.as_json() for c in candidates):
        raise PermissionDenied("A selected source changed or is no longer accessible.")


def merge_receipt(receipts: dict, data: dict) -> dict:
    key = str(data["delivery_id"])
    previous = receipts.get(key)
    if data["status"] != "dispatching" and previous is None:
        raise ValidationError("A terminal receipt requires a matching dispatch receipt.")
    if previous:
        if any(previous[field] != data[field] for field in ("prompt", "prompt_hash", "context_included")):
            raise ValidationError("A delivery cannot change its archived prompt.")
        if previous["status"] in ("completed", "failed"):
            if previous["status"] != data["status"]:
                raise ValidationError("A delivery cannot change its terminal status.")
            return receipts
    elif len(receipts) >= 20:
        raise ValidationError("Too many dispatch attempts.")
    now = timezone.now().isoformat()
    payload = {k: str(v) if k.endswith("_id") else v for k, v in data.items()}
    events = list(previous.get("events", [])) if previous else []
    if not previous or previous["status"] != data["status"]:
        events.append({"status": data["status"], "recorded_at": now})
    return {**receipts, key: {**payload, "recorded_at": now, "events": events}}
