from django.db import close_old_connections

import structlog
from temporalio import activity

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.tasks.failure_handler import (
    FAILURE_TYPE_USER,
    classify_rasterization_failure,
    rasterization_failure_message,
)

from ..types import RecordRasterizationFailureInput
from .rasterize import report_export_event

logger = structlog.get_logger(__name__)


@activity.defn
def record_rasterization_failure(inputs: RecordRasterizationFailureInput) -> None:
    """Persist why a render failed and report it, so the asset is a terminal state rather than a gap.

    Without this the row keeps `has_content=False` and no exception forever, which reads identically
    to a render that is still working.
    """
    close_old_connections()

    asset = ExportedAsset.objects.select_related("team__organization", "created_by").get(pk=inputs.exported_asset_id)

    if asset.exception:
        # Keep the first reason recorded. A later sweep or retry has less information than whichever
        # attempt actually saw the failure.
        return

    failure_type = classify_rasterization_failure(inputs.error_code)

    asset.exception = rasterization_failure_message(inputs.error_code)
    asset.exception_type = inputs.error_code
    asset.failure_type = failure_type
    asset.save(update_fields=["exception", "exception_type", "failure_type"])

    logger.warning(
        "rasterization_failed",
        asset_id=asset.id,
        error_code=inputs.error_code,
        failure_type=failure_type,
        error_message=inputs.error_message,
    )

    report_export_event(
        asset,
        "export failed",
        error=inputs.error_message,
        error_code=inputs.error_code,
        failure_type=failure_type,
        # Named to match what the other export formats report, so failures compare across all of them.
        is_user_error=failure_type == FAILURE_TYPE_USER,
    )
