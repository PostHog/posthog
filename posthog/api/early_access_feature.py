from typing import Type

from django.http import JsonResponse
from posthog.api.feature_flag import MinimalFeatureFlagSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.utils import get_token
from posthog.exceptions import generate_exception_response
from posthog.models.early_access_feature import EarlyAccessFeature
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework import status, response

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.team.team import Team
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

from posthog.utils import cors_response
from typing import Any


class MinimalEarlyAccessFeatureSerializer(serializers.ModelSerializer):
    """
    A more minimal serializer, intended specificaly for non-generally-available features to be provided
    to posthog-js via the /early_access_features/ endpoint. Sync with posthog-js's FeaturePreview interface!
    """

    documentationUrl = serializers.URLField(source="documentation_url")
    flagKey = serializers.CharField(source="feature_flag.key")

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "name",
            "description",
            "stage",
            "documentationUrl",
            "flagKey",
        ]
        read_only_fields = fields


class EarlyAccessFeatureSerializer(serializers.ModelSerializer):
    feature_flag = MinimalFeatureFlagSerializer(read_only=True)

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "feature_flag",
            "name",
            "description",
            "stage",
            "documentation_url",
            "created_at",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]


class EarlyAccessFeatureSerializerCreateOnly(EarlyAccessFeatureSerializer):
    feature_flag_id = serializers.IntegerField(required=False, write_only=True)

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "name",
            "description",
            "stage",
            "documentation_url",
            "created_at",
            "feature_flag_id",
            "feature_flag",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]

        feature_flag_id = validated_data.get("feature_flag_id", None)

        default_condition = [
            {"properties": [], "rollout_percentage": 100, "variant": None},
        ]
        super_conditions = lambda feature_flag_key: [
            {
                "properties": [
                    {
                        "key": f"$feature_enrollment/{feature_flag_key}",
                        "type": "person",
                        "operator": "is_set",
                    },
                ],
                "rollout_percentage": 100,
            },
        ]

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
                    "groups": default_condition,
                    "payloads": {},
                    "multivariate": None,
                    "super_groups": super_conditions(feature_flag_key),
                },
            )
            feature_flag_key = feature_flag.key
        validated_data["feature_flag_id"] = feature_flag.id
        feature: EarlyAccessFeature = super().create(validated_data)
        feature_flag.filters = {
            "groups": feature_flag.filters.get("groups", default_condition),
            "payloads": {},
            "multivariate": None,
            "super_groups": super_conditions(feature_flag_key),
        }
        feature_flag.save()
        return feature


class EarlyAccessFeatureViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):  # TODO: Use ForbidDestroyModel
    queryset = EarlyAccessFeature.objects.select_related("feature_flag").all()
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    def get_serializer_class(self) -> Type[serializers.Serializer]:
        if self.request.method == "POST":
            return EarlyAccessFeatureSerializerCreateOnly
        else:
            return EarlyAccessFeatureSerializer

    @action(methods=["POST"], detail=True)
    def promote(self, request: Request, *args: Any, **kwargs: Any):
        early_access_feature: EarlyAccessFeature = self.get_object()
        early_access_feature.promote()
        res = EarlyAccessFeatureSerializer(early_access_feature, many=False).data
        return response.Response(res, status=status.HTTP_200_OK)


@csrf_exempt
def early_access_features(request: Request):

    token = get_token(None, request)

    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "early_access_features",
                "API key not provided. You can find your project API key in PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    team = Team.objects.get_team_from_cache_or_token(token)
    if team is None:
        return cors_response(
            request,
            generate_exception_response(
                "decide",
                "Project API key invalid. You can find your project API key in PostHog project settings.",
                type="authentication_error",
                code="invalid_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    early_access_features = MinimalEarlyAccessFeatureSerializer(
        EarlyAccessFeature.objects.filter(team_id=team.id)
        .exclude(stage=EarlyAccessFeature.Stage.GENERAL_AVAILABILITY)
        .select_related("feature_flag"),
        many=True,
    ).data

    return cors_response(request, JsonResponse({"earlyAccessFeatures": early_access_features}))
