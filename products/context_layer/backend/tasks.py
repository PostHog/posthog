from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from celery import shared_task

from posthog.models.scoping import team_scope

from products.context_layer.backend.models import ContextSelectionAttempt, ContextSelectionProjection
from products.context_layer.backend.selection_sources import projection_key, refresh_projection


@shared_task(ignore_result=True)
def refresh_context_selection_projection(team_id: int) -> None:
    if team_id not in settings.CONTEXT_SELECTION_ALLOWED_TEAM_IDS:
        return
    try:
        with team_scope(team_id):
            refresh_projection(team_id)
    finally:
        cache.delete(f"{projection_key(team_id)}:refresh")


@shared_task(ignore_result=True)
def purge_context_selection_attempts() -> None:
    ContextSelectionAttempt.objects.unscoped().filter(expires_at__lte=timezone.now()).delete()
    ContextSelectionProjection.objects.unscoped().filter(expires_at__lte=timezone.now()).delete()
