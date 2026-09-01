from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from uuid import UUID

from django.db.models import Q, QuerySet

from posthog.permissions import posthog_feature_flag_value

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.ai_observability.backend.dataset_limits import MAX_DATASET_EXPORT_BYTES, MAX_DATASET_EXPORT_MEGABYTES
from products.ai_observability.backend.dataset_queries import dataset_item_versions_at_revision
from products.ai_observability.backend.models.datasets import Dataset, DatasetItemVersion, DatasetRevision
from products.exports.backend.facade.api import (
    ExportedAsset,
    InvalidExportContext,
    RetryableExportError,
    save_export_asset_content_from_file,
)

DATASETS_FEATURE_FLAG = "llm-analytics-datasets"
DATASET_EXPORT_DATABASE_FALLBACK_BYTES = 50_000_000
DATASET_EXPORT_BATCH_SIZE = 50


DatasetExportError = InvalidExportContext


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _export_row(version: DatasetItemVersion, *, selected_revision: DatasetRevision) -> dict[str, object]:
    item = version.dataset_item
    return {
        "dataset_id": str(selected_revision.dataset_id),
        "dataset_revision": selected_revision.revision,
        "item_id": str(item.id),
        "client_item_id": item.client_item_id,
        "version": version.version,
        "input": version.input,
        "expected_output": version.expected_output,
        "source_output": version.source_output,
        "metadata": version.metadata,
        "source_trace_id": version.source_trace_id,
        "source_event_id": version.source_event_id,
        "source_timestamp": _isoformat(version.source_timestamp),
    }


def _iter_versions_in_batches(
    versions: QuerySet[DatasetItemVersion, DatasetItemVersion],
) -> Iterator[DatasetItemVersion]:
    last_created_at: datetime | None = None
    last_item_id: UUID | None = None

    while True:
        page = versions
        if last_created_at is not None and last_item_id is not None:
            page = page.filter(
                Q(dataset_item__created_at__gt=last_created_at)
                | Q(dataset_item__created_at=last_created_at, dataset_item_id__gt=last_item_id)
            )
        batch = list(page[:DATASET_EXPORT_BATCH_SIZE])
        if not batch:
            return

        yield from batch
        last_version = batch[-1]
        last_created_at = last_version.dataset_item.created_at
        last_item_id = last_version.dataset_item_id


def export_dataset_jsonl(asset: ExportedAsset) -> None:
    context = asset.export_context or {}
    try:
        dataset_id = UUID(str(context["dataset_id"]))
        revision = int(context["dataset_revision"])
    except (KeyError, TypeError, ValueError) as error:
        raise DatasetExportError("The dataset export configuration is invalid.") from error

    if not asset.is_dataset_export or revision < 1 or asset.created_by is None:
        raise DatasetExportError("The dataset export configuration is invalid.")

    dataset = Dataset.objects.for_team(asset.team_id, canonical=True).filter(id=dataset_id).first()
    if dataset is None:
        raise DatasetExportError("The dataset is no longer available.")
    if not UserAccessControl(user=asset.created_by, team=asset.team).check_access_level_for_object(dataset, "viewer"):
        raise DatasetExportError("You no longer have access to this dataset.")
    feature_flag_value = posthog_feature_flag_value(
        DATASETS_FEATURE_FLAG,
        str(asset.created_by.distinct_id),
        organization_id=asset.team.organization_id,
        team_id=asset.team_id,
    )
    if feature_flag_value is None:
        raise RetryableExportError("Couldn't verify whether dataset exports are available. Try again.")
    if not feature_flag_value:
        raise DatasetExportError("Dataset exports are not available for this project.")
    selected_revision = (
        DatasetRevision.objects.for_team(asset.team_id, canonical=True)
        .filter(
            dataset_id=dataset.id,
            revision=revision,
        )
        .first()
    )
    if selected_revision is None:
        raise DatasetExportError("The selected dataset revision is no longer available.")

    versions = (
        dataset_item_versions_at_revision(
            team_id=asset.team_id,
            dataset_id=dataset.id,
            revision=revision,
            archived=False,
        )
        .select_related("dataset_item")
        .order_by("dataset_item__created_at", "dataset_item_id")
    )

    file_path: str | None = None
    try:
        total_bytes = 0
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".jsonl", delete=False) as export_file:
            file_path = export_file.name
            for version in _iter_versions_in_batches(versions):
                line = (
                    json.dumps(
                        _export_row(version, selected_revision=selected_revision),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
                total_bytes += len(line)
                if total_bytes > MAX_DATASET_EXPORT_BYTES:
                    raise DatasetExportError(
                        f"The dataset export is larger than {MAX_DATASET_EXPORT_MEGABYTES} MB. "
                        "Reduce the number or size of items and try again."
                    )
                export_file.write(line)
        save_export_asset_content_from_file(
            asset=asset,
            file_path=file_path,
            max_database_bytes=DATASET_EXPORT_DATABASE_FALLBACK_BYTES,
        )
    finally:
        if file_path is not None:
            Path(file_path).unlink(missing_ok=True)
