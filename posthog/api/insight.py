from typing import Any, Dict

from django.db.models import QuerySet
from rest_framework import serializers, viewsets

from posthog.models import Insight


class InsightSerializer(serializers.ModelSerializer):
    class Meta:
        model = Insight
        fields = ["id", "name", "filters", "created_at", "pinned"]

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Insight:
        request = self.context["request"]
        annotation = Insight.objects.create(team=request.user.team_set.get(), **validated_data)
        return annotation


class InsightViewSet(viewsets.ModelViewSet):
    queryset = Insight.objects.all()
    serializer_class = InsightSerializer

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        team = self.request.user.team_set.get()

        if self.action == "list":  # type: ignore
            order = self.request.GET.get("order", None)
            if order:
                queryset = queryset.order_by(order)

        return queryset.filter(team=team)
