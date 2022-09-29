from typing import Any

from django.db.models import Q, QuerySet
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import ActivityLog, FeatureFlag, Insight


class ActivityLogSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer()

    class Meta:
        model = ActivityLog
        exclude = ["team_id"]


class ActivityLogViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    queryset = ActivityLog.objects.all()
    serializer_class = ActivityLogSerializer
    default_limit = 500

    def filter_queryset_by_parents_lookups(self, queryset) -> QuerySet:
        team = self.team
        return queryset.filter(Q(organization_id=team.organization_id) | Q(team_id=team.id))

    @action(methods=["GET"], detail=False)
    def important_changes(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        my_insights = list(Insight.objects.filter(created_by=self.request.user).values_list("id", flat=True))
        my_feature_flags = list(FeatureFlag.objects.filter(created_by=self.request.user).values_list("id", flat=True))
        other_peoples_changes = (
            self.queryset.filter(scope__in=["FeatureFlag", "Insight"])
            .exclude(user=self.request.user)
            .filter(
                Q(Q(scope="FeatureFlag") & Q(item_id__in=my_feature_flags))
                | Q(Q(scope="Insight") & Q(item_id__in=my_insights))
            )
            .order_by("-created_at")
        )[:10]
        serialized_data = ActivityLogSerializer(instance=other_peoples_changes, many=True).data
        return Response(status=status.HTTP_200_OK, data=serialized_data)
