from rest_framework import viewsets, serializers
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import QuerySet
from posthog.models import Feature
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin


class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = [
            "id",
            "name",
            "description",
            "documentation_url",
            "issue_url",
            "primary_early_access_feature_id",
            "created_at",
            "updated_at",
            "archived",
            "deleted",
        ]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data)

    def get_primary_early_access_feature(self, feature: Feature):
        from posthog.api.early_access_feature import EarlyAccessFeatureSerializer

        return EarlyAccessFeatureSerializer(feature.primary_early_access_feature, context=self.context).data

    def get_early_access_features(self, feature: Feature):
        from posthog.api.early_access_feature import EarlyAccessFeatureSerializer

        return EarlyAccessFeatureSerializer(feature.earlyaccessfeature_set, many=True).data

    def get_experiments(self, feature: Feature):
        from posthog.api.web_experiment import WebExperimentsAPISerializer

        return WebExperimentsAPISerializer(feature.experiment_set, many=True).data

    def get_feature_flags(self, feature: Feature):
        from posthog.api.feature_flag import MinimalFeatureFlagSerializer

        return MinimalFeatureFlagSerializer(feature.featureflag_set, context=self.context, many=True).data


class FeatureViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "feature"
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer

    def safely_get_queryset(self, queryset) -> QuerySet:
        # Base queryset with team filtering
        queryset = Feature.objects.filter(team_id=self.team_id)

        if self.action == "primary_early_access_feature":
            queryset = queryset.select_related("primary_early_access_feature")
        elif self.action == "experiments":
            queryset = queryset.prefetch_related("experiment_set")
        elif self.action == "early_access_features":
            queryset = queryset.prefetch_related("earlyaccessfeature_set")
        elif self.action == "feature_flags":
            queryset = queryset.prefetch_related("featureflag_set")

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
    def feature_flags(self, request, pk=None, **kwargs):
        """
        Get all feature flags associated with a specific feature.
        """
        feature = self.get_object()
        flags = FeatureSerializer().get_feature_flags(feature)
        return Response(flags)

    @action(detail=True, methods=["get"])
    def experiments(self, request, pk=None, **kwargs):
        """
        Get experiments associated with a specific feature.
        """
        feature = self.get_object()
        experiments = FeatureSerializer().get_experiments(feature)
        return Response(experiments)

    @action(detail=True, methods=["get"])
    def early_access_features(self, request, pk=None, **kwargs):
        """
        Get early access features associated with a specific feature.
        """
        feature = self.get_object()
        early_access_features = FeatureSerializer().get_early_access_features(feature)
        return Response(early_access_features)
