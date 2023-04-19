from typing import Type
from posthog.api.feature_flag import MinimalFeatureFlagSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models.feature import Feature
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from django.utils.text import slugify


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
            "id",
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
    feature_flag_id = serializers.IntegerField(required=False, write_only=True)

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
            "feature_flag_id",
            "feature_flag",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]

        feature_flag_id = validated_data.get("feature_flag_id", None)

        if feature_flag_id:
            feature_flag = FeatureFlag.objects.get(pk=feature_flag_id)
            feature_flag_key = feature_flag.key
        else:
            feature_flag_key = slugify(validated_data["name"])
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
            feature_flag_key = feature_flag.key
        validated_data["feature_flag_id"] = feature_flag.id

        feature: Feature = super().create(validated_data)
        feature_flag.filters = {
            "groups": [
                *feature_flag.filters["groups"],
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
                },
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
