from typing import Dict, Optional

import posthoganalytics
from rest_framework import response, status


class AnalyticsDestroyModelMixin:
    """
    Destroy a model instance sending analytics information.
    """

    def perform_destroy(self, instance):
        instance.delete()

    def destroy(self, request, *args, **kwgars):

        instance = self.get_object()  # type: ignore
        self.perform_destroy(instance)

        metadata: Optional[Dict] = instance.get_analytics_metadata() if hasattr(
            instance, "get_analytics_metadata",
        ) else None

        posthoganalytics.capture(
            request.user.distinct_id, f"{instance._meta.verbose_name} deleted", metadata,
        )

        return response.Response(status=status.HTTP_204_NO_CONTENT)
