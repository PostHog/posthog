from dataclasses import field
from datetime import datetime
from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
type ResultValue = float | bool | list[str]
type RunSource = Literal["ci", "local", "scheduled"]
type ResultStatus = Literal["ok", "error", "skipped", "not_applicable"]


@frozen
class ExperimentSubmission:
    id: UUID
    name: str
    started_at: datetime
    run_source: RunSource | None = None
    expected_item_count: int | None = None
    expected_result_count: int | None = None
    suite_key: str | None = None
    dataset_source: str | None = None
    dataset_identifier: str | None = None
    dataset_revision_identifier: str | None = None
    dataset_revision_id: UUID | None = None
    application_version: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None


@frozen
class ItemSubmission:
    id: UUID
    case_key: str | None = None
    trial: str | None = None
    dataset_item_identifier: str | None = None
    dataset_item_version_identifier: str | None = None
    dataset_item_version_id: UUID | None = None
    application_trace_id: str | None = None
    payload: dict[str, JSONValue] | None = field(default=None, repr=False)


@frozen
class ResultSubmission:
    item_id: UUID
    scorer_version_id: UUID
    status: ResultStatus
    value: ResultValue | None = None
    error_code: str | None = None
    evaluator_trace_id: str | None = None
    evaluated_at: datetime | None = None
    payload: dict[str, JSONValue] | None = field(default=None, repr=False)


@frozen
class UploadSubmission:
    results: list[ResultSubmission]
    items: list[ItemSubmission] = field(default_factory=list)
