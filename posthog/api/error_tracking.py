from django.db.models import QuerySet
from rest_framework import serializers, viewsets

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.error_tracking import ErrorTrackingGroup


class ErrorTrackingGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingGroup
        fields = [
            "assignee",
        ]

    def update(self, instance: ErrorTrackingGroup, validated_data: dict, **kwargs) -> ErrorTrackingGroup:
        instance.assignee = validated_data["assignee"]
        instance.save()
        return instance


class ErrorTrackingGroupViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "error_tracking_group"
    queryset = ErrorTrackingGroup.objects.all()
    serializer_class = ErrorTrackingGroupSerializer

    def safely_get_object(self, queryset) -> QuerySet:
        fingerprint = self.kwargs["pk"]
        groups = ErrorTrackingGroup.filter_fingerprints(queryset=queryset, fingerprints=[fingerprint])

        if groups:
            return groups.first()

        # lazily creates error group if it does not already exist
        return ErrorTrackingGroup.objects.create(team=self.team, fingerprint=fingerprint)
