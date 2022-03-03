from typing import Any

import structlog
from rest_framework import response, status

from posthog.event_usage import report_user_action
from posthog.models import HistoricalVersion

logger = structlog.get_logger(__name__)


def _should_save_historical_version(instance: Any) -> bool:
    return instance.__class__.__name__ in ["FeatureFlag"]


class AnalyticsDestroyModelMixin:
    """
    DestroyModelMixin enhancement that provides reporting of when an object is deleted.

    Generally this would be better off executed at the serializer level,
    but deletion (i.e. `destroy`) is performed directly in the viewset, which is why this mixin is a thing.
    """

    def perform_destroy(self, instance):
        instance.delete()

    def destroy(self, request, *args, **kwargs):

        instance = self.get_object()  # type: ignore

        metadata = instance.get_analytics_metadata() if hasattr(instance, "get_analytics_metadata",) else {}

        self.perform_destroy(instance)

        report_user_action(request.user, f"{instance._meta.verbose_name} deleted", metadata)

        if _should_save_historical_version(instance) and metadata:
            """
            This is mixed in to API view sets so has team_id available
            """
            team_id = self.team_id  # type:ignore
            HistoricalVersion.save_deletion(
                instance=instance, item_id=kwargs["pk"], team_id=team_id, user=request.user,
            )

        return response.Response(status=status.HTTP_204_NO_CONTENT)
