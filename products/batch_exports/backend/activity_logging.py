"""Activity-log receiver for BatchExport changes.

Kept in its own import-light module so the batch_exports AppConfig can wire it at
ready() without importing the API module (which pulls DRF, the batch export service
layer, and the Temporal client). The Temporal batch-export service mutates BatchExport
directly (pause/unpause), so the receiver must be connected in every process — workers
included — not just where the API loads.
"""

import dataclasses

from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.batch_exports.backend.models.batch_export import BatchExport


@dataclasses.dataclass(frozen=True)
class BatchExportContext(ActivityContextBase):
    name: str
    destination_type: str
    interval: str
    created_by_user_id: str | None
    created_by_user_email: str | None
    created_by_user_name: str | None


@mutable_receiver(model_activity_signal, sender=BatchExport)
def handle_batch_export_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    from posthog.models.activity_logging.batch_export_utils import (  # noqa: PLC0415
        get_batch_export_created_by_info,
        get_batch_export_destination_type,
        get_batch_export_detail_name,
    )

    # Use after_update for create/update, before_update for delete
    batch_export = after_update or before_update

    if not batch_export:
        return

    destination_type = get_batch_export_destination_type(batch_export)
    created_by_user_id, created_by_user_email, created_by_user_name = get_batch_export_created_by_info(batch_export)
    detail_name = get_batch_export_detail_name(batch_export, destination_type)

    context = BatchExportContext(
        name=batch_export.name or "Unnamed Export",
        destination_type=destination_type,
        interval=batch_export.interval or "",
        created_by_user_id=created_by_user_id,
        created_by_user_email=created_by_user_email,
        created_by_user_name=created_by_user_name,
    )

    log_activity(
        organization_id=batch_export.team.organization_id,
        team_id=batch_export.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=batch_export.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )
