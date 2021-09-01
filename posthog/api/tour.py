from rest_framework import viewsets

from posthog.api.routing import StructuredViewSetMixin
from posthog.mixins import AnalyticsDestroyModelMixin


class TourSerializer:
    pass


class TourViewSet(StructuredViewSetMixin, AnalyticsDestroyModelMixin, viewsets.ModelViewSet):
    pass
