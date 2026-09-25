import json
import base64
import binascii
from dataclasses import field
from datetime import datetime
from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen

from products.ai_observability.backend.offline_evaluation_service import OfflineEvaluationValidationError
from products.ai_observability.backend.offline_evaluation_types import JSONValue, ResultValue


def encode_cursor(values: list[str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_cursor(cursor: str, expected_parts: int) -> list[str]:
    try:
        if len(cursor) > 2048:
            raise ValueError
        decoded = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if (
            not isinstance(decoded, list)
            or len(decoded) != expected_parts
            or not all(isinstance(v, str) for v in decoded)
        ):
            raise ValueError
        return decoded
    except (ValueError, UnicodeDecodeError, binascii.Error) as error:
        raise OfflineEvaluationValidationError("cursor", "Provide a valid continuation cursor.") from error


@frozen
class OfflineReadQuery:
    limit: int = 50
    cursor: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    search: str | None = None
    run_source: str | None = None
    run_source_is_null: bool = False
    statuses: tuple[str, ...] | None = None
    suite_key: str | None = None
    dataset_source: str | None = None
    dataset_identifier: str | None = None
    dataset_revision_identifier: str | None = None
    application_version: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    scorer_definition_id: UUID | None = None
    scorer_version_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise OfflineEvaluationValidationError("limit", "Use a page size between 1 and 100.")
        if len(self.scorer_version_ids) > 20 or len(set(self.scorer_version_ids)) != len(self.scorer_version_ids):
            raise OfflineEvaluationValidationError("scorer_version_ids", "Select at most 20 distinct scorer versions.")
        if self.date_from is not None and self.date_to is not None and self.date_from > self.date_to:
            raise OfflineEvaluationValidationError("date_to", "The end time must not precede the start time.")


@frozen
class OfflinePage[T]:
    count: int
    next_cursor: str | None
    results: list[T]


@frozen
class OfflineExperimentRead:
    id: UUID
    name: str
    run_source: str | None
    status: str
    started_at: datetime
    created_at: datetime
    finished_at: datetime | None
    expected_item_count: int | None
    expected_result_count: int | None
    accepted_item_count: int
    visible_result_count: int | None
    visible_scorer_definition_count: int | None
    visible_scorer_version_count: int | None
    result_counts_available: bool
    result_count_scope: Literal["authorized", "unavailable"]
    suite_key: str | None
    dataset_source: str | None
    dataset_identifier: str | None
    dataset_revision_identifier: str | None
    dataset_revision_id: UUID | None
    application_version: str | None
    model_version: str | None
    prompt_version: str | None


@frozen
class OfflineScorerVersionRead:
    id: UUID
    definition_id: UUID
    version: int
    kind: str
    name: str
    description: str
    archived: bool
    config: dict[str, JSONValue]


@frozen
class OfflineResultRead:
    id: UUID
    item_id: UUID
    scorer: OfflineScorerVersionRead
    status: str
    value: ResultValue | None
    error_code: str | None
    evaluator_trace_id: str | None
    evaluated_at: datetime | None
    accepted_at: datetime
    payload_state: str
    payload_expires_at: datetime | None


@frozen
class OfflineItemRead:
    id: UUID
    experiment_id: UUID
    case_key: str | None
    trial: str | None
    dataset_item_identifier: str | None
    dataset_item_version_identifier: str | None
    dataset_item_version_id: UUID | None
    application_trace_id: str | None
    accepted_at: datetime
    payload_state: str
    payload_expires_at: datetime | None
    results: list[OfflineResultRead] = field(default_factory=list)


@frozen
class OfflinePayloadRead:
    id: UUID
    payload_state: str
    payload_expires_at: datetime | None
    available: bool
    data: dict[str, JSONValue] | None = field(repr=False)


@frozen
class OfflineStatusCounts:
    ok: int
    error: int
    skipped: int
    not_applicable: int


@frozen
class OfflineCategorySummary:
    key: str
    label: str
    count: int
    rate: float | None


@frozen
class OfflineScorerSummary:
    scorer: OfflineScorerVersionRead
    observed_item_count: int
    result_count: int
    status_counts: OfflineStatusCounts
    missing_result_count: int
    distinct_case_count: int
    items_with_case_key_count: int
    items_without_case_key_count: int
    trial_item_count: int
    distinct_trial_count: int
    mean: float | None
    true_count: int | None
    false_count: int | None
    true_rate: float | None
    categories: list[OfflineCategorySummary]


@frozen
class OfflineHistoryPoint:
    experiment: OfflineExperimentRead
    summary: OfflineScorerSummary
