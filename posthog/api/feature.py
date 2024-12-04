from rest_framework import viewsets, serializers
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404

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
            "status",
            "primary_feature_flag_id",
            "created_at",
            "updated_at",
            "archived",
            "deleted",
        ]

    def get_primary_feature_flag(self, feature: Feature):
        from posthog.api.feature_flag import MinimalFeatureFlagSerializer

        return MinimalFeatureFlagSerializer(feature.primary_feature_flag).data

    def get_early_access_features(self, feature: Feature):
        from posthog.api.early_access_feature import MinimalEarlyAccessFeatureSerializer

        return MinimalEarlyAccessFeatureSerializer(feature.earlyaccessfeature_set, many=True).data

    def get_experiments(self, feature: Feature):
        from posthog.api.web_experiment import WebExperimentsAPISerializer

        return WebExperimentsAPISerializer(feature.experiment_set, many=True).data

    def get_feature_flags(self, feature: Feature):
        from posthog.api.feature_flag import MinimalFeatureFlagSerializer

        return MinimalFeatureFlagSerializer(feature.featureflag_set, many=True).data


class FeatureViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    """
    Create, read, update and delete Features.
    """

    serializer_class = FeatureSerializer

    @action(detail=True, methods=["get"])
    def primary_feature_flag(self, request, pk=None):
        """
        Get primary feature flag associated with a specific feature.
        """
        feature = get_object_or_404(
            Feature.objects.select_related("primary_feature_flag"), team_id=self.team_id, pk=pk, deleted=False
        )
        primary_feature_flag = self.get_serializer().get_primary_feature_flag(feature)
        return Response(primary_feature_flag)

    @action(detail=True, methods=["get"])
    def feature_flags(self, request, pk=None):
        """
        Get all feature flags associated with a specific feature.
        """
        feature = get_object_or_404(
            Feature.objects.select_related("featureflag_set"), team_id=self.team_id, pk=pk, deleted=False
        )
        flags = self.get_serializer().get_feature_flags(feature)
        return Response(flags)

    @action(detail=True, methods=["get"])
    def experiments(self, request, pk=None):
        """
        Get experiments associated with a specific feature.
        """
        feature = get_object_or_404(
            Feature.objects.prefetch_related("experiment_set"), team_id=self.team_id, pk=pk, deleted=False
        )
        experiments = self.get_serializer().get_experiments(feature)
        return Response(experiments)

    @action(detail=True, methods=["get"])
    def early_access_features(self, request, pk=None):
        """
        Get early access features associated with a specific feature.
        """
        feature = get_object_or_404(
            Feature.objects.prefetch_related("earlyaccessfeature_set"), team_id=self.team_id, pk=pk, deleted=False
        )
        early_access_features = self.get_serializer().get_early_access_features(feature)
        return Response(early_access_features)
