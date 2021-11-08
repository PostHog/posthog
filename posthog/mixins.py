from typing import Dict, Optional

import posthoganalytics
from rest_framework import response, status


class AnalyticsDestroyModelMixin:
    """
    DestroyModelMixin enhancement that provides reporting of when an object is deleted.

    Generally this would be better off executed at the serializer level,
    but deletion (i.e. `destroy`) is performed directly in the viewset, which is why this mixin is a thing.
    """

    def perform_destroy(self, instance):
        instance.delete()

    def destroy(self, request, *args, **kwgars):

        instance = self.get_object()  # type: ignore

        metadata: Optional[Dict] = instance.get_analytics_metadata() if hasattr(
            instance, "get_analytics_metadata",
        ) else None

        self.perform_destroy(instance)

        posthoganalytics.capture(
            request.user.distinct_id, f"{instance._meta.verbose_name} deleted", metadata,
        )

        return response.Response(status=status.HTTP_204_NO_CONTENT)
