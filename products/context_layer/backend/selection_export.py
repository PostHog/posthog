import json
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.storage import object_storage

from products.context_layer.backend.models import ContextSelectionAttempt, ContextSelectionProjection
from products.tasks.backend.models import TaskRun


def selection_gaps(attempt: ContextSelectionAttempt) -> list[str]:
    gaps = []
    if attempt.status == "preparing":
        gaps.append("selection_incomplete")
    if not attempt.receipt:
        gaps.append("no_delivery_receipt")
    for receipt in attempt.receipt.values():
        if receipt["status"] == "dispatching":
            gaps.append("delivery_outcome_unknown")
        if receipt["status"] == "completed" and not receipt.get("trace_id"):
            gaps.append("missing_turn_trace")
        if receipt["status"] == "completed" and not receipt.get("usage"):
            gaps.append("missing_usage")
    return sorted(set(gaps))


def export_selections(team_id: int, task_id: UUID) -> dict:
    if team_id not in settings.CONTEXT_SELECTION_ALLOWED_TEAM_IDS:
        raise ValueError("Only configured internal projects can be exported.")
    with team_scope(team_id):
        attempts = list(ContextSelectionAttempt.objects.filter(run__task_id=task_id).order_by("created_at"))
        archive_ids = {a.evidence.get("projection", {}).get("archive_id") for a in attempts}
        archives = {
            str(p.id): p.payload
            for p in ContextSelectionProjection.objects.filter(id__in=[id for id in archive_ids if id])
        }
        runs = TaskRun.objects.filter(team_id=team_id, task_id=task_id).order_by("created_at")
        trajectories = []
        for run in runs:
            gaps = []
            try:
                raw = object_storage.read(run.log_url, missing_ok=True)
                if not raw:
                    gaps.append("missing_or_empty_log")
            except Exception as error:
                raw = None
                gaps.append(type(error).__name__)
            malformed = 0
            if raw:
                for line in raw.splitlines():
                    if line.strip():
                        try:
                            json.loads(line)
                        except ValueError:
                            malformed += 1
            if malformed:
                gaps.append("malformed_jsonl")
            if run.status not in (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED):
                gaps.append("run_not_terminal")
            trajectories.append(
                {
                    "run_id": str(run.id),
                    "resume_from_run_id": (run.state or {}).get("resume_from_run_id"),
                    "status": run.status,
                    "raw_jsonl": raw,
                    "malformed_lines": malformed,
                    "gaps": gaps,
                    "coverage": "persisted_run_log_not_provider_transcript",
                }
            )
        return {
            "schema_version": 1,
            "exported_at": timezone.now().isoformat(),
            "retention": {
                "selection_days": 90,
                "default_run_log_days": 30,
                "complete_export_window": "before_earliest_run_log_expiry_or_task_deletion",
            },
            "team_id": team_id,
            "task_id": str(task_id),
            "projections": archives,
            "missing_projection_ids": sorted(str(id) for id in archive_ids if id and str(id) not in archives),
            "trajectories": trajectories,
            "feedback_join": {"web_run_key": "run_id", "slack_run_key": "task_run_id", "trace_key": "$ai_trace_id"},
            "selections": [
                {
                    "selection_id": str(a.id),
                    "run_id": str(a.run_id),
                    "message_id": a.message_id,
                    "mode": a.mode,
                    "status": a.status,
                    "evidence": a.evidence,
                    "receipts": a.receipt,
                    "created_at": a.created_at.isoformat(),
                    "expires_at": a.expires_at.isoformat(),
                    "gaps": selection_gaps(a),
                }
                for a in attempts
            ],
        }
