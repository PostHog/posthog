from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

from posthog.permissions import posthog_feature_flag_enabled
from posthog.rbac.user_access_control import UserAccessControl

from products.ai_observability.backend.dataset_queries import dataset_item_versions_at_revision
from products.ai_observability.backend.models.datasets import Dataset, DatasetItemVersion, DatasetRevision
from products.exports.backend.models.exported_asset import ExportedAsset, save_content_from_file

DATASETS_FEATURE_FLAG = "llm-analytics-datasets"
DATASET_EXPORT_DATABASE_FALLBACK_BYTES = 50_000_000


class DatasetExportError(Exception):
    pass


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _export_row(version: DatasetItemVersion, *, selected_revision: DatasetRevision) -> dict[str, object]:
    item = version.dataset_item
    return {
        "dataset_id": str(selected_revision.dataset_id),
        "dataset_revision": selected_revision.revision,
        "dataset_revision_id": str(selected_revision.id),
        "item_id": str(item.id),
        "client_item_id": item.client_item_id,
        "version_id": str(version.id),
        "version": version.version,
        "version_dataset_revision": version.dataset_revision.revision,
        "version_dataset_revision_id": str(version.dataset_revision_id),
        "archived": version.archived,
        "input": version.input,
        "expected_output": version.expected_output,
        "source_output": version.source_output,
        "metadata": version.metadata,
        "source_trace_id": version.source_trace_id,
        "source_event_id": version.source_event_id,
        "source_timestamp": _isoformat(version.source_timestamp),
        "item_created_at": _isoformat(item.created_at),
        "version_created_at": _isoformat(version.created_at),
        "item_created_by_id": item.created_by_id,
        "version_created_by_id": version.created_by_id,
    }


def export_dataset_jsonl(asset: ExportedAsset) -> None:
    context = asset.export_context or {}
    try:
        dataset_id = UUID(str(context["dataset_id"]))
        revision = int(context["dataset_revision"])
    except (KeyError, TypeError, ValueError) as error:
        raise DatasetExportError("The dataset export configuration is invalid.") from error

    if revision < 1 or asset.created_by is None:
        raise DatasetExportError("The dataset export configuration is invalid.")

    dataset = Dataset.objects.for_team(asset.team_id, canonical=True).filter(id=dataset_id).first()
    if dataset is None:
        raise DatasetExportError("The dataset is no longer available.")
    if not UserAccessControl(user=asset.created_by, team=asset.team).check_access_level_for_object(dataset, "viewer"):
        raise DatasetExportError("You no longer have access to this dataset.")
    if not posthog_feature_flag_enabled(
        DATASETS_FEATURE_FLAG,
        str(asset.created_by.distinct_id),
        organization_id=asset.team.organization_id,
        team_id=asset.team_id,
    ):
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
        .select_related("dataset_item", "dataset_revision")
        .order_by("dataset_item__created_at", "dataset_item_id")
    )

    file_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".jsonl", delete=False) as export_file:
            file_path = export_file.name
            for version in versions.iterator(chunk_size=50):
                export_file.write(
                    json.dumps(
                        _export_row(version, selected_revision=selected_revision),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                export_file.write("\n")
        save_content_from_file(
            asset,
            file_path,
            max_database_bytes=DATASET_EXPORT_DATABASE_FALLBACK_BYTES,
        )
    finally:
        if file_path is not None:
            Path(file_path).unlink(missing_ok=True)
