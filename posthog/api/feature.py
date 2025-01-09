from rest_framework import viewsets, serializers
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import QuerySet
from posthog.models import Feature, FeatureAlertConfiguration
from posthog.api.alert import AlertSerializer
from posthog.api.early_access_feature import EarlyAccessFeatureSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin


class FeatureAlertConfigurationSerializer(serializers.ModelSerializer):
    alert_configuration = AlertSerializer()

    class Meta:
        model = FeatureAlertConfiguration
        fields = ["alert_configuration", "feature_insight_type"]


class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = [
            "id",
            "name",
            "description",
            "primary_early_access_feature_id",
            "created_at",
            "created_by",
            "archived",
            "deleted",
        ]

    def create(self, validated_data):
        request = self.context["request"]

        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["primary_early_access_feature_id"] = request.data.get("primary_early_access_feature_id")
        return super().create(validated_data)

    def get_primary_early_access_feature(self, feature: Feature):
        return EarlyAccessFeatureSerializer(feature.primary_early_access_feature, context=self.context).data


class FeatureViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "feature"
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer

    def safely_get_queryset(self, queryset) -> QuerySet:
        # Base queryset with team filtering
        queryset = Feature.objects.filter(team_id=self.team_id)

        if self.action == "primary_early_access_feature":
            queryset = queryset.select_related("primary_early_access_feature")
        elif self.action == "alerts":
            queryset = queryset.prefetch_related("alerts")

        return queryset

    @action(detail=True, methods=["get"])
    def primary_early_access_feature(self, request, pk=None, **kwargs):
        """
        Get primary feature flag associated with a specific feature.
        """
        feature = self.get_object()
        primary_early_access_feature = FeatureSerializer().get_primary_early_access_feature(feature)
        return Response(primary_early_access_feature)

    @action(detail=True, methods=["get"])
    def alerts(self, request, pk=None, **kwargs):
        """
        Get all alerts associated with a specific feature. These alerts are used to track
        success and failure metrics for the feature.
        """
        feature = self.get_object()
        alerts_for_feature = FeatureAlertConfiguration.objects.filter(feature=feature).all()
        alerts = FeatureAlertConfigurationSerializer(alerts_for_feature, many=True).data
        return Response(alerts)
