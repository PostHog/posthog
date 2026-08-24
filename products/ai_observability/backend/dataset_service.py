from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Max

from posthog.models import Team, User

from products.ai_observability.backend.dataset_limits import MAX_DATASET_ITEM_PAYLOAD_BYTES, MAX_ITEMS_PER_DATASET
from products.ai_observability.backend.dataset_queries import latest_dataset_revision
from products.ai_observability.backend.models.datasets import Dataset, DatasetItem, DatasetItemVersion, DatasetRevision

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]

MAX_DATASET_METADATA_BYTES = 1_000_000
MAX_DATASET_DESCRIPTION_LENGTH = 10_000
MAX_DATASET_NAME_LENGTH = 400
MAX_CLIENT_ITEM_ID_LENGTH = 255
MAX_SOURCE_ID_LENGTH = 255
MAX_DATASETS_PER_TEAM = 20
MAX_VERSIONS_PER_ITEM = 40


class DatasetValidationError(Exception):
    def __init__(self, field: str, detail: str) -> None:
        super().__init__(detail)
        self.field = field
        self.detail = detail


class DatasetMutationConflict(Exception):
    def __init__(
        self,
        *,
        code: Literal[
            "dataset_archived",
            "dataset_name_conflict",
            "dataset_item_archived",
            "dataset_item_active",
            "client_item_id_conflict",
            "stale_version",
        ],
        detail: str,
        current_version: int | None = None,
        current_item_id: UUID | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.current_version = current_version
        self.current_item_id = current_item_id


class DatasetLimitExceeded(Exception):
    code: Literal["limit_reached"] = "limit_reached"

    def __init__(
        self,
        *,
        resource: Literal["datasets", "dataset_items", "dataset_item_versions"],
        current_count: int,
        limit: int,
        detail: str,
    ) -> None:
        super().__init__(detail)
        self.resource = resource
        self.current_count = current_count
        self.limit = limit
        self.detail = detail


class DatasetIntegrityError(Exception):
    pass


class _Unset:
    pass


UNSET = _Unset()


@dataclass(frozen=True)
class _DatasetItemContent:
    input: JSONValue
    expected_output: JSONValue
    source_output: JSONValue
    metadata: dict[str, JSONValue]
    source_trace_id: str | None
    source_event_id: str | None
    source_timestamp: datetime | None

    @classmethod
    def from_version(cls, version: DatasetItemVersion) -> _DatasetItemContent:
        return cls(
            input=version.input,
            expected_output=version.expected_output,
            source_output=version.source_output,
            metadata=version.metadata,
            source_trace_id=version.source_trace_id,
            source_event_id=version.source_event_id,
            source_timestamp=version.source_timestamp,
        )


@dataclass(frozen=True)
class DatasetItemMutationResult:
    item: DatasetItem
    version: DatasetItemVersion
    created: bool = True


def _json_size(value: JSONValue | dict[str, JSONValue], *, field: str, limit: int) -> None:
    try:
        payload_size = len(
            json.dumps(
                value,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as error:
        raise DatasetValidationError(field, "Enter a valid JSON value.") from error

    if payload_size > limit:
        raise DatasetValidationError(field, f"This field must be {limit} bytes or fewer.")


def _json_values_equal(left: JSONValue, right: JSONValue) -> bool:
    return json.dumps(left, separators=(",", ":"), ensure_ascii=False, sort_keys=True) == json.dumps(
        right,
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
    )


def _validate_metadata(metadata: dict[str, JSONValue], *, field: str = "metadata") -> None:
    if not isinstance(metadata, dict):
        raise DatasetValidationError(field, "Enter a JSON object.")
    _json_size(metadata, field=field, limit=MAX_DATASET_METADATA_BYTES)


def _validate_dataset_fields(*, name: str, description: str, metadata: dict[str, JSONValue]) -> str:
    normalized_name = name.strip()
    if not normalized_name:
        raise DatasetValidationError("name", "Enter a dataset name.")
    if len(normalized_name) > MAX_DATASET_NAME_LENGTH:
        raise DatasetValidationError("name", f"Dataset names must be {MAX_DATASET_NAME_LENGTH} characters or fewer.")
    if len(description) > MAX_DATASET_DESCRIPTION_LENGTH:
        raise DatasetValidationError(
            "description",
            f"Dataset descriptions must be {MAX_DATASET_DESCRIPTION_LENGTH} characters or fewer.",
        )
    _validate_metadata(metadata)
    return normalized_name


def _validate_item_content(
    *,
    content: _DatasetItemContent,
) -> None:
    if content.input is None:
        raise DatasetValidationError("input", "Input cannot be null.")

    _validate_metadata(content.metadata)

    if content.source_trace_id == "":
        raise DatasetValidationError("source_trace_id", "Source trace ID cannot be blank.")
    if content.source_event_id == "":
        raise DatasetValidationError("source_event_id", "Source event ID cannot be blank.")
    if content.source_trace_id is not None and len(content.source_trace_id) > MAX_SOURCE_ID_LENGTH:
        raise DatasetValidationError(
            "source_trace_id",
            f"Source trace IDs must be {MAX_SOURCE_ID_LENGTH} characters or fewer.",
        )
    if content.source_event_id is not None and len(content.source_event_id) > MAX_SOURCE_ID_LENGTH:
        raise DatasetValidationError(
            "source_event_id",
            f"Source event IDs must be {MAX_SOURCE_ID_LENGTH} characters or fewer.",
        )
    if content.source_trace_id is None and (
        content.source_event_id is not None or content.source_timestamp is not None
    ):
        raise DatasetValidationError(
            "source_trace_id",
            "Provide a source trace ID when using a source event ID or timestamp.",
        )
    if content.source_trace_id is not None and content.source_timestamp is None:
        raise DatasetValidationError(
            "source_timestamp",
            "Provide the source timestamp when using a source trace ID.",
        )

    _json_size(
        {
            "input": content.input,
            "expected_output": content.expected_output,
            "source_output": content.source_output,
            "metadata": content.metadata,
        },
        field="item",
        limit=MAX_DATASET_ITEM_PAYLOAD_BYTES,
    )


def _item_contents_equal(left: _DatasetItemContent, right: _DatasetItemContent) -> bool:
    return (
        _json_values_equal(left.input, right.input)
        and _json_values_equal(left.expected_output, right.expected_output)
        and _json_values_equal(left.source_output, right.source_output)
        and _json_values_equal(left.metadata, right.metadata)
        and left.source_trace_id == right.source_trace_id
        and left.source_event_id == right.source_event_id
        and left.source_timestamp == right.source_timestamp
    )


def _validate_client_item_id(client_item_id: str | None) -> None:
    if client_item_id is None:
        return
    if not client_item_id:
        raise DatasetValidationError("client_item_id", "Client item ID cannot be blank.")
    if len(client_item_id) > MAX_CLIENT_ITEM_ID_LENGTH:
        raise DatasetValidationError(
            "client_item_id",
            f"Client item IDs must be {MAX_CLIENT_ITEM_ID_LENGTH} characters or fewer.",
        )


def _lock_dataset(*, team_id: int, dataset_id: UUID) -> Dataset:
    dataset = (
        Dataset.objects.for_team(team_id, canonical=True)
        .select_for_update(of=("self",))
        .select_related("current_revision")
        .get(id=dataset_id)
    )
    current_revision = dataset.current_revision
    if current_revision is None:
        current_revision = latest_dataset_revision(team_id=dataset.team_id, dataset_id=dataset.id)
        if current_revision is not None:
            dataset.current_revision = current_revision
            dataset.save(update_fields=["current_revision"])
    if current_revision is not None and (
        current_revision.dataset_id != dataset.id or current_revision.team_id != dataset.team_id
    ):
        raise DatasetIntegrityError("Dataset current revision has inconsistent ownership.")
    return dataset


def _lock_item(*, team_id: int, dataset: Dataset, item_id: UUID) -> DatasetItem:
    item = (
        DatasetItem.objects.for_team(team_id, canonical=True)
        .select_for_update(of=("self",))
        .select_related("current_version", "current_version__dataset_revision")
        .get(id=item_id, dataset_id=dataset.id)
    )
    _current_item_version(dataset=dataset, item=item)
    return item


def _validate_item_version_ownership(
    *,
    dataset: Dataset,
    item: DatasetItem,
    version: DatasetItemVersion,
) -> None:
    if (
        item.team_id != dataset.team_id
        or item.dataset_id != dataset.id
        or version.team_id != dataset.team_id
        or version.dataset_id != dataset.id
        or version.dataset_item_id != item.id
        or version.dataset_revision.dataset_id != dataset.id
        or version.dataset_revision.team_id != dataset.team_id
    ):
        raise DatasetIntegrityError("Dataset item version has inconsistent ownership.")


def _current_item_version(*, dataset: Dataset, item: DatasetItem) -> DatasetItemVersion:
    version = item.current_version
    if version is None:
        version = (
            DatasetItemVersion.objects.for_team(dataset.team_id, canonical=True)
            .select_related("dataset_revision")
            .filter(dataset_item_id=item.id)
            .order_by("-version")
            .first()
        )
        if version is None:
            raise DatasetIntegrityError("Dataset item has no current version.")
        item.current_version = version
        item.save(update_fields=["current_version"])
    _validate_item_version_ownership(dataset=dataset, item=item, version=version)
    return version


def _check_base_version(*, current_version: DatasetItemVersion, base_version: int) -> None:
    if current_version.version != base_version:
        raise DatasetMutationConflict(
            code="stale_version",
            detail="This dataset item changed after it was loaded. Reload it and try again.",
            current_version=current_version.version,
            current_item_id=current_version.dataset_item_id,
        )


def _create_revision(*, dataset: Dataset, created_by: User | None) -> DatasetRevision:
    latest_revision_number = (
        DatasetRevision.objects.for_team(dataset.team_id, canonical=True)
        .filter(dataset_id=dataset.id)
        .aggregate(latest_revision=Max("revision"))["latest_revision"]
        or 0
    )
    return DatasetRevision.objects.for_team(dataset.team_id, canonical=True).create(
        team_id=dataset.team_id,
        dataset=dataset,
        revision=latest_revision_number + 1,
        created_by=created_by,
    )


def _create_item_version(
    *,
    dataset: Dataset,
    item: DatasetItem,
    created_by: User | None,
    version_number: int,
    archived: bool,
    content: _DatasetItemContent,
    reserve_restore_slot: bool = False,
) -> DatasetItemVersion:
    if item.team_id != dataset.team_id or item.dataset_id != dataset.id:
        raise DatasetIntegrityError("Dataset item has inconsistent ownership.")

    current_count = (
        DatasetItemVersion.objects.for_team(dataset.team_id, canonical=True)
        .filter(
            dataset_id=dataset.id,
            dataset_item_id=item.id,
        )
        .count()
    )
    version_limit = MAX_VERSIONS_PER_ITEM - int(reserve_restore_slot)
    if current_count >= version_limit:
        detail = (
            f"This dataset item cannot be archived because the last version slot is reserved for restoring it. "
            f"The limit is {MAX_VERSIONS_PER_ITEM}. Create a new item to continue."
            if reserve_restore_slot
            else (
                f"No more versions can be added to this dataset item. The limit is {MAX_VERSIONS_PER_ITEM}. "
                "Create a new item to continue."
            )
        )
        raise DatasetLimitExceeded(
            resource="dataset_item_versions",
            current_count=current_count,
            limit=MAX_VERSIONS_PER_ITEM,
            detail=detail,
        )

    revision = _create_revision(dataset=dataset, created_by=created_by)
    version = DatasetItemVersion.objects.for_team(dataset.team_id, canonical=True).create(
        team_id=dataset.team_id,
        dataset=dataset,
        dataset_item=item,
        dataset_revision=revision,
        version=version_number,
        archived=archived,
        input=content.input,
        expected_output=content.expected_output,
        source_output=content.source_output,
        metadata=content.metadata,
        source_trace_id=content.source_trace_id,
        source_event_id=content.source_event_id,
        source_timestamp=content.source_timestamp,
        created_by=created_by,
    )

    item.current_version = version
    item.save(update_fields=["current_version", "updated_at"])
    dataset.current_revision = revision
    dataset.save(update_fields=["current_revision", "updated_at"])
    return version


@transaction.atomic
def create_dataset(
    *,
    team: Team,
    created_by: User | None,
    name: str,
    description: str = "",
    metadata: dict[str, JSONValue] | None = None,
) -> Dataset:
    normalized_metadata = metadata if metadata is not None else {}
    normalized_name = _validate_dataset_fields(name=name, description=description, metadata=normalized_metadata)
    Team.objects.select_for_update().only("id").get(id=team.id)
    current_count = Dataset.objects.for_team(team.id, canonical=True).count()
    if current_count >= MAX_DATASETS_PER_TEAM:
        raise DatasetLimitExceeded(
            resource="datasets",
            current_count=current_count,
            limit=MAX_DATASETS_PER_TEAM,
            detail=(
                f"No more datasets can be added to this project. The limit is {MAX_DATASETS_PER_TEAM}. "
                "Contact support if you need more."
            ),
        )
    try:
        return Dataset.objects.for_team(team.id, canonical=True).create(
            team=team,
            created_by=created_by,
            name=normalized_name,
            description=description,
            metadata=normalized_metadata,
        )
    except IntegrityError as error:
        raise DatasetMutationConflict(
            code="dataset_name_conflict",
            detail="A dataset with this name already exists.",
        ) from error


@transaction.atomic
def update_dataset(
    *,
    team_id: int,
    dataset_id: UUID,
    name: str | _Unset = UNSET,
    description: str | _Unset = UNSET,
    metadata: dict[str, JSONValue] | _Unset = UNSET,
) -> Dataset:
    dataset = _lock_dataset(team_id=team_id, dataset_id=dataset_id)
    if dataset.archived:
        raise DatasetMutationConflict(
            code="dataset_archived",
            detail="Restore this dataset before updating it.",
        )

    next_name = dataset.name if isinstance(name, _Unset) else name
    next_description = dataset.description if isinstance(description, _Unset) else description
    next_metadata = dataset.metadata if isinstance(metadata, _Unset) else metadata
    normalized_name = _validate_dataset_fields(
        name=next_name,
        description=next_description,
        metadata=next_metadata,
    )

    update_fields = ["updated_at"]
    if not isinstance(name, _Unset):
        dataset.name = normalized_name
        update_fields.append("name")
    if not isinstance(description, _Unset):
        dataset.description = description
        update_fields.append("description")
    if not isinstance(metadata, _Unset):
        dataset.metadata = metadata
        update_fields.append("metadata")
    try:
        dataset.save(update_fields=update_fields)
    except IntegrityError as error:
        raise DatasetMutationConflict(
            code="dataset_name_conflict",
            detail="A dataset with this name already exists.",
        ) from error
    return dataset


@transaction.atomic
def archive_dataset(*, team_id: int, dataset_id: UUID) -> Dataset:
    dataset = _lock_dataset(team_id=team_id, dataset_id=dataset_id)
    if dataset.archived:
        return dataset
    dataset.archived = True
    dataset.save(update_fields=["archived", "updated_at"])
    return dataset


@transaction.atomic
def restore_dataset(*, team_id: int, dataset_id: UUID) -> Dataset:
    dataset = _lock_dataset(team_id=team_id, dataset_id=dataset_id)
    if not dataset.archived:
        return dataset
    dataset.archived = False
    dataset.save(update_fields=["archived", "updated_at"])
    return dataset


@transaction.atomic
def create_dataset_item(
    *,
    team_id: int,
    dataset_id: UUID,
    created_by: User | None,
    input: JSONValue,
    expected_output: JSONValue = None,
    source_output: JSONValue = None,
    metadata: dict[str, JSONValue] | None = None,
    client_item_id: str | None = None,
    source_trace_id: str | None = None,
    source_event_id: str | None = None,
    source_timestamp: datetime | None = None,
) -> DatasetItemMutationResult:
    normalized_metadata = metadata if metadata is not None else {}
    content = _DatasetItemContent(
        input=input,
        expected_output=expected_output,
        source_output=source_output,
        metadata=normalized_metadata,
        source_trace_id=source_trace_id,
        source_event_id=source_event_id,
        source_timestamp=source_timestamp,
    )
    _validate_client_item_id(client_item_id)
    _validate_item_content(content=content)

    dataset = _lock_dataset(team_id=team_id, dataset_id=dataset_id)
    if dataset.archived:
        raise DatasetMutationConflict(
            code="dataset_archived",
            detail="Restore this dataset before adding items.",
        )

    if client_item_id is not None:
        existing_item = (
            DatasetItem.objects.for_team(team_id, canonical=True)
            .select_related("current_version", "current_version__dataset_revision")
            .filter(dataset=dataset, client_item_id=client_item_id)
            .first()
        )
        if existing_item is not None:
            current_version = _current_item_version(dataset=dataset, item=existing_item)
            if current_version.archived:
                raise DatasetMutationConflict(
                    code="client_item_id_conflict",
                    detail="An archived item already uses this client item ID. Unarchive that item to use it again.",
                    current_version=current_version.version,
                    current_item_id=existing_item.id,
                )
            if _item_contents_equal(_DatasetItemContent.from_version(current_version), content):
                return DatasetItemMutationResult(
                    item=existing_item,
                    version=current_version,
                    created=False,
                )
            raise DatasetMutationConflict(
                code="client_item_id_conflict",
                detail="An item with this client item ID already exists with different content.",
                current_version=current_version.version,
                current_item_id=existing_item.id,
            )

    current_count = DatasetItem.objects.for_team(dataset.team_id, canonical=True).filter(dataset=dataset).count()
    if current_count >= MAX_ITEMS_PER_DATASET:
        raise DatasetLimitExceeded(
            resource="dataset_items",
            current_count=current_count,
            limit=MAX_ITEMS_PER_DATASET,
            detail=(
                f"No more items can be added to this dataset. The limit is {MAX_ITEMS_PER_DATASET}. "
                "Contact support if you need more."
            ),
        )

    item = DatasetItem.objects.for_team(dataset.team_id, canonical=True).create(
        team_id=dataset.team_id,
        dataset=dataset,
        client_item_id=client_item_id,
        created_by=created_by,
    )
    version = _create_item_version(
        dataset=dataset,
        item=item,
        created_by=created_by,
        version_number=1,
        archived=False,
        content=content,
    )
    return DatasetItemMutationResult(item=item, version=version)


@transaction.atomic
def update_dataset_item(
    *,
    team_id: int,
    dataset_id: UUID,
    item_id: UUID,
    created_by: User | None,
    base_version: int,
    input: JSONValue | _Unset = UNSET,
    expected_output: JSONValue | _Unset = UNSET,
    metadata: dict[str, JSONValue] | _Unset = UNSET,
) -> DatasetItemMutationResult:
    dataset = _lock_dataset(team_id=team_id, dataset_id=dataset_id)
    if dataset.archived:
        raise DatasetMutationConflict(
            code="dataset_archived",
            detail="Restore this dataset before updating its items.",
        )
    item = _lock_item(team_id=team_id, dataset=dataset, item_id=item_id)
    current_version = _current_item_version(dataset=dataset, item=item)
    _check_base_version(current_version=current_version, base_version=base_version)
    if current_version.archived:
        raise DatasetMutationConflict(
            code="dataset_item_archived",
            detail="Restore this dataset item before updating it.",
            current_version=current_version.version,
            current_item_id=item.id,
        )

    current_content = _DatasetItemContent.from_version(current_version)
    next_content = replace(
        current_content,
        input=current_content.input if isinstance(input, _Unset) else input,
        expected_output=current_content.expected_output if isinstance(expected_output, _Unset) else expected_output,
        metadata=current_content.metadata if isinstance(metadata, _Unset) else metadata,
    )
    _validate_item_content(content=next_content)

    if _item_contents_equal(current_content, next_content):
        return DatasetItemMutationResult(
            item=item,
            version=current_version,
            created=False,
        )

    version = _create_item_version(
        dataset=dataset,
        item=item,
        created_by=created_by,
        version_number=current_version.version + 1,
        archived=False,
        content=next_content,
    )
    return DatasetItemMutationResult(item=item, version=version)


@transaction.atomic
def archive_dataset_item(
    *,
    team_id: int,
    dataset_id: UUID,
    item_id: UUID,
    created_by: User | None,
    base_version: int,
) -> DatasetItemMutationResult:
    dataset = _lock_dataset(team_id=team_id, dataset_id=dataset_id)
    if dataset.archived:
        raise DatasetMutationConflict(
            code="dataset_archived",
            detail="Restore this dataset before archiving its items.",
        )
    item = _lock_item(team_id=team_id, dataset=dataset, item_id=item_id)
    current_version = _current_item_version(dataset=dataset, item=item)
    _check_base_version(current_version=current_version, base_version=base_version)
    if current_version.archived:
        raise DatasetMutationConflict(
            code="dataset_item_archived",
            detail="This dataset item is already archived.",
            current_version=current_version.version,
            current_item_id=item.id,
        )

    version = _create_item_version(
        dataset=dataset,
        item=item,
        created_by=created_by,
        version_number=current_version.version + 1,
        archived=True,
        content=_DatasetItemContent.from_version(current_version),
        reserve_restore_slot=True,
    )
    return DatasetItemMutationResult(item=item, version=version)


@transaction.atomic
def restore_dataset_item(
    *,
    team_id: int,
    dataset_id: UUID,
    item_id: UUID,
    created_by: User | None,
    base_version: int,
    source_version: int | None = None,
) -> DatasetItemMutationResult:
    dataset = _lock_dataset(team_id=team_id, dataset_id=dataset_id)
    if dataset.archived:
        raise DatasetMutationConflict(
            code="dataset_archived",
            detail="Restore this dataset before restoring its items.",
        )
    item = _lock_item(team_id=team_id, dataset=dataset, item_id=item_id)
    current_version = _current_item_version(dataset=dataset, item=item)
    _check_base_version(current_version=current_version, base_version=base_version)
    if not current_version.archived:
        raise DatasetMutationConflict(
            code="dataset_item_active",
            detail="This dataset item is already active.",
            current_version=current_version.version,
            current_item_id=item.id,
        )

    restored_version = current_version
    if source_version is not None:
        restored_version = DatasetItemVersion.objects.for_team(team_id, canonical=True).get(
            dataset_id=dataset.id,
            dataset_item=item,
            version=source_version,
        )
        _validate_item_version_ownership(dataset=dataset, item=item, version=restored_version)

    restored_content = replace(
        _DatasetItemContent.from_version(restored_version),
        source_output=current_version.source_output,
        source_trace_id=current_version.source_trace_id,
        source_event_id=current_version.source_event_id,
        source_timestamp=current_version.source_timestamp,
    )

    version = _create_item_version(
        dataset=dataset,
        item=item,
        created_by=created_by,
        version_number=current_version.version + 1,
        archived=False,
        content=restored_content,
    )
    return DatasetItemMutationResult(item=item, version=version)
