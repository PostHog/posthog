from posthog.api.feature_flag import FeatureFlagBasicSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.feature import Feature
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class FeaturePreviewSerializer(serializers.ModelSerializer):
    """
    A more minimal feature serializer, intended specificaly for non-generally-available features to be provided
    to posthog-js via the decide endpoint. Sync with posthog-js's FeaturePreview interface!
    """

    imageUrl = serializers.URLField(source="image_url")
    documentationUrl = serializers.URLField(source="documentation_url")
    flagKey = serializers.CharField(source="feature_flag.key")

    class Meta:
        model = Feature
        fields = [
            "name",
            "description",
            "status",
            "imageUrl",
            "documentationUrl",
            "flagKey",
        ]
        read_only_fields = fields


class FeatureSerializer(serializers.ModelSerializer):
    feature_flag = FeatureFlagBasicSerializer(read_only=True)

    class Meta:
        model = Feature
        fields = [
            "id",
            "feature_flag",
            "name",
            "description",
            "status",
            "image_url",
            "documentation_url",
            "created_at",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data)


class FeatureViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):  # TODO: Use ForbidDestroyModel
    queryset = Feature.objects.select_related("feature_flag").all()
    serializer_class = FeatureSerializer
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]
