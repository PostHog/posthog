from typing import Any

from django.utils import timezone

from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.surveys.survey_recommendation import SurveyRecommendation


class SurveyRecommendationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveyRecommendation
        fields = "__all__"
        read_only_fields = [f.name for f in SurveyRecommendation._meta.fields if f.name != "status"]


class SurveyRecommendationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "survey"
    queryset = SurveyRecommendation.objects.all()
    serializer_class = SurveyRecommendationSerializer

    # only get/list and patch (for status updates)
    http_method_names = ["get", "patch"]

    def safely_get_queryset(self, queryset):
        # default - only show active
        status_filter = self.request.query_params.get("status", "active")
        if status_filter != "all":
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by("-score", "-created_at")

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()

        # only status can be updated. recommendations are largely immutable
        new_status = request.data.get("status")
        if new_status not in [SurveyRecommendation.Status.DISMISSED, SurveyRecommendation.Status.CONVERTED]:
            return Response(
                {"detail": "Can only update status to 'dismissed' or 'converted'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance.status = new_status
        if new_status == SurveyRecommendation.Status.DISMISSED:
            instance.dismissed_at = timezone.now()

        instance.save()
        return Response(self.get_serializer(instance).data)
