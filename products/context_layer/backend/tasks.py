from django.conf import settings
from django.utils import timezone

from celery import shared_task

from posthog.models.scoping import team_scope

from products.context_layer.backend.models import (
    ContextSelectionAttempt,
    ContextSelectionProjection,
    ContextSelectionSearchState,
)
from products.context_layer.backend.selection_sources import refresh_projection


@shared_task(ignore_result=True)
def refresh_context_selection_projection(team_id: int) -> None:
    if team_id not in settings.CONTEXT_SELECTION_ALLOWED_TEAM_IDS:
        return
    with team_scope(team_id):
        refresh_projection(team_id)


@shared_task(ignore_result=True)
def refresh_all_context_selection_projections() -> None:
    for team_id in settings.CONTEXT_SELECTION_ALLOWED_TEAM_IDS:
        refresh_context_selection_projection.delay(team_id)


@shared_task(ignore_result=True)
def purge_context_selection_attempts() -> None:
    now = timezone.now()
    ContextSelectionAttempt.objects.unscoped().filter(expires_at__lte=now).delete()
    current_ids = ContextSelectionSearchState.objects.unscoped().values_list("archive_id", flat=True)
    expired = ContextSelectionProjection.objects.unscoped().filter(expires_at__lte=now).exclude(id__in=current_ids)
    for archive in expired.iterator():
        if (
            not ContextSelectionAttempt.objects.unscoped()
            .filter(expires_at__gt=now, evidence__projection__archive_id=str(archive.id))
            .exists()
        ):
            archive.delete()
