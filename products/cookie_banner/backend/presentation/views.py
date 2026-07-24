"""DRF views for cookie_banner."""

from django.db.models import QuerySet

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.cookie_banner.backend.models import CookieBannerConfig
from products.cookie_banner.backend.presentation.serializers import CookieBannerConfigSerializer


class CookieBannerConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Manage the project's cookie banner. A project has at most one banner,
    so list returns zero or one items and create fails once one exists.
    """

    scope_object = "cookie_banner"
    queryset = CookieBannerConfig.objects.unscoped()
    serializer_class = CookieBannerConfigSerializer
    permission_classes = [IsAuthenticated]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # Project-wide, not team_id: the row lives on the project's root team even when
        # the request comes through a child environment's URL
        return queryset.filter(team__project_id=self.project_id)
