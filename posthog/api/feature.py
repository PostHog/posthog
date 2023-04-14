from typing import Type
from posthog.api.feature_flag import MinimalFeatureFlagSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.feature import Feature
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from posthog.models.feature_flag.feature_flag import FeatureFlag
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
            "stage",
            "imageUrl",
            "documentationUrl",
            "flagKey",
        ]
        read_only_fields = fields


class FeatureSerializer(serializers.ModelSerializer):
    feature_flag = MinimalFeatureFlagSerializer(read_only=True)

    class Meta:
        model = Feature
        fields = [
            "id",
            "feature_flag",
            "name",
            "description",
            "stage",
            "image_url",
            "documentation_url",
            "created_at",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]


class FeatureSerializerCreateOnly(FeatureSerializer):
    feature_flag_key = serializers.CharField(
        max_length=FeatureFlag._meta.get_field("key").max_length, required=True, write_only=True
    )

    class Meta:
        model = Feature
        fields = [
            "id",
            "name",
            "description",
            "stage",
            "image_url",
            "documentation_url",
            "created_at",
            "feature_flag",
            "feature_flag_key",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        feature_flag_key = validated_data.pop("feature_flag_key")
        feature_flag = FeatureFlag.objects.create(
            team_id=self.context["team_id"],
            key=feature_flag_key,
            name=f"Feature Flag for Feature {validated_data['name']}",
            created_by=self.context["request"].user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": f"$feature_enrollment/{feature_flag_key}",
                                "type": "person",
                                "value": ["true"],
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ],
                "payloads": {},
                "multivariate": None,
            },
        )
        validated_data["feature_flag_id"] = feature_flag.id

        feature: Feature = super().create(validated_data)
        feature_flag.filters = {
            "groups": [
                {
                    "properties": [
                        {
                            "key": f"$feature_enrollment/{feature_flag_key}",
                            "type": "person",
                            "value": ["true"],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 100,
                    "feature_preview": str(feature.pk),
                }
            ],
            "payloads": {},
            "multivariate": None,
        }
        feature_flag.save()
        return feature


class FeatureViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):  # TODO: Use ForbidDestroyModel
    queryset = Feature.objects.select_related("feature_flag").all()
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    def get_serializer_class(self) -> Type[serializers.Serializer]:
        if self.request.method == "POST":
            return FeatureSerializerCreateOnly
        else:
            return FeatureSerializer
