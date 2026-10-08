import json
import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from products.ai_observability.backend.offline_evaluation_types import (
    ExperimentSubmission,
    ItemSubmission,
    ResultSubmission,
)


def _normalize(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _normalize(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_normalize(child) for child in value]
    return value


def submission_fingerprint(submission: ExperimentSubmission | ItemSubmission | ResultSubmission) -> str:
    # This format must stay stable across deployments and after payload deletion.
    content = json.dumps(_normalize(asdict(submission)), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(b"offline-evaluation:v1:" + content.encode("utf-8")).hexdigest()
