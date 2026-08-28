from datetime import timedelta
from typing import Literal

from django.utils.timezone import now

from rest_framework import serializers

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

from products.ai_observability.backend.api.dataset_serializers import StrictDatasetSerializer
from products.ai_observability.backend.dataset_queries import latest_dataset_revision
from products.ai_observability.backend.models.datasets import Dataset, DatasetRevision
from products.exports.backend.facade.api import (
    DATASET_EXPORT_KIND,
    EXPORT_WORKFLOW_TIMEOUT,
    JSONL_EXPORT_FORMAT,
    ExportedAsset,
    create_export_asset_async,
    get_export_asset,
)

DATASET_EXPORT_STUCK_AFTER = EXPORT_WORKFLOW_TIMEOUT + timedelta(seconds=30)
DATASET_EXPORT_STUCK_MESSAGE = "This export took too long to finish. Try again. If it keeps failing, contact support."


class DatasetExportUnavailableError(Exception):
    pass


class DatasetExportCreateSerializer(StrictDatasetSerializer):
    revision = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Dataset revision to export. Defaults to the latest revision when the export is created.",
    )


class DatasetExportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the export cannot be created or downloaded yet.")


class DatasetExportReadSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="Export ID used to check status and download the file.")
    status = serializers.SerializerMethodField(help_text="Current export state: pending, complete, or failed.")
    dataset_revision = serializers.SerializerMethodField(help_text="Immutable dataset revision included in the export.")
    filename = serializers.CharField(read_only=True, help_text="Generated JSONL filename.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the export was requested.")
    expires_after = serializers.DateTimeField(read_only=True, help_text="When the generated file expires.")
    exception = serializers.SerializerMethodField(
        help_text="Reason the export failed, or null while it is pending or complete.",
    )

    def get_status(self, asset: ExportedAsset) -> Literal["pending", "complete", "failed"]:
        if get_dataset_export_effective_exception(asset):
            return "failed"
        if asset.has_content:
            return "complete"
        return "pending"

    def get_dataset_revision(self, asset: ExportedAsset) -> int:
        return int((asset.export_context or {})["dataset_revision"])

    def get_exception(self, asset: ExportedAsset) -> str | None:
        return get_dataset_export_effective_exception(asset)


def get_dataset_export_effective_exception(asset: ExportedAsset) -> str | None:
    if asset.exception:
        return asset.exception
    if not asset.has_content and asset.created_at < now() - DATASET_EXPORT_STUCK_AFTER:
        return DATASET_EXPORT_STUCK_MESSAGE
    return None


def create_dataset_export(
    *,
    dataset: Dataset,
    team: Team,
    created_by: User,
    was_impersonated: bool,
    revision: int | None,
) -> ExportedAsset:
    selected_revision = revision
    if selected_revision is None:
        latest_revision = latest_dataset_revision(team_id=team.id, dataset_id=dataset.id)
        if latest_revision is None:
            raise DatasetExportUnavailableError("Add an item before exporting this dataset.")
        selected_revision = latest_revision.revision
    elif (
        not DatasetRevision.objects.for_team(team.id, canonical=True)
        .filter(
            dataset_id=dataset.id,
            revision=selected_revision,
        )
        .exists()
    ):
        raise DatasetExportUnavailableError("This dataset revision does not exist.")

    asset = create_export_asset_async(
        team=team,
        created_by=created_by,
        export_format=JSONL_EXPORT_FORMAT,
        export_context={
            "kind": DATASET_EXPORT_KIND,
            "dataset_id": str(dataset.id),
            "dataset_revision": selected_revision,
            "filename": f"{dataset.name}-r{selected_revision}",
        },
    )
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=created_by,
        was_impersonated=was_impersonated,
        item_id=asset.id,
        scope="ExportedAsset",
        activity="exported",
        detail=Detail(
            name=f"{dataset.name}-r{selected_revision}",
            type=DATASET_EXPORT_KIND,
            changes=[
                Change(
                    type="ExportedAsset",
                    action="exported",
                    field="export_format",
                    after=JSONL_EXPORT_FORMAT,
                )
            ],
        ),
    )
    return asset


def get_dataset_export(
    *,
    dataset: Dataset,
    team_id: int,
    user_id: int,
    asset_id: int,
) -> ExportedAsset | None:
    asset = get_export_asset(team_id=team_id, asset_id=asset_id)
    if asset is None or asset.created_by_id != user_id or not asset.is_dataset_export:
        return None
    context = asset.export_context or {}
    if str(context.get("dataset_id")) != str(dataset.id):
        return None
    return asset
