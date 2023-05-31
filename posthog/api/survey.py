from typing import Type

from posthog.api.shared import UserBasicSerializer
from posthog.models.feedback.survey import Survey
from rest_framework.response import Response
from posthog.api.feature_flag import FeatureFlagSerializer, MinimalFeatureFlagSerializer
from posthog.api.routing import StructuredViewSetMixin
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from django.utils.text import slugify

from typing import Any


class SurveySerializer(serializers.ModelSerializer):
    linked_flag = MinimalFeatureFlagSerializer(read_only=True)
    targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Survey
        fields = [
            "id",
            "name",
            "description",
            "type",
            "linked_flag",
            "targeting_flag",
            "questions",
            "conditions",
            "appearance",
            "created_at",
            "created_by",
            "start_date",
            "end_date",
            "archived",
        ]
        read_only_fields = ["id", "created_at", "created_by"]


class SurveySerializerCreateUpdateOnly(SurveySerializer):
    linked_flag_id = serializers.IntegerField(required=False, write_only=True)
    targeting_flag_id = serializers.IntegerField(required=False, write_only=True)
    targeting_flag_filters = serializers.JSONField(required=False, write_only=True)

    class Meta:
        model = Survey
        fields = [
            "id",
            "name",
            "description",
            "type",
            "linked_flag",
            "linked_flag_id",
            "targeting_flag_id",
            "targeting_flag",
            "targeting_flag_filters",
            "questions",
            "conditions",
            "appearance",
            "created_at",
            "created_by",
            "start_date",
            "end_date",
        ]
        read_only_fields = ["id", "linked_flag", "targeting_flag", "created_at"]

    def validate(self, data):
        linked_flag_id = data.get("linked_flag_id", None)
        if linked_flag_id:
            try:
                FeatureFlag.objects.get(pk=linked_flag_id)
            except FeatureFlag.DoesNotExist:
                raise serializers.ValidationError("Feature Flag with this ID does not exist")

        if Survey.objects.filter(name=data.get("name", None), team_id=self.context["team_id"]).exists():
            raise serializers.ValidationError("There is already a survey with this name.", code="unique")

        return data

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        if validated_data.get("targeting_flag_filters", None):
            targeting_feature_flag = self._create_new_targeting_flag(
                validated_data["name"], validated_data["targeting_flag_filters"]
            )
            validated_data["targeting_flag_id"] = targeting_feature_flag.id
            validated_data.pop("targeting_flag_filters")

        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)

    def update(self, instance: Survey, validated_data):
        # if the target flag filters come back with data, update the targeting feature flag if there is one, otherwise create a new one
        if validated_data.get("targeting_flag_filters", None):
            if instance.targeting_flag:
                existing_targeting_flag = instance.targeting_flag
                serialized_data_filters = {
                    **existing_targeting_flag.filters,
                    **validated_data["targeting_flag_filters"],
                }
                existing_flag_serializer = FeatureFlagSerializer(
                    existing_targeting_flag,
                    data={"filters": serialized_data_filters},
                    partial=True,
                    context=self.context,
                )
                existing_flag_serializer.is_valid(raise_exception=True)
                existing_flag_serializer.save()
            else:
                new_flag = self._create_new_targeting_flag(instance.name, validated_data["targeting_flag_filters"])
                validated_data["targeting_flag_id"] = new_flag.id
            validated_data.pop("targeting_flag_filters")
        return super().update(instance, validated_data)

    def _create_new_targeting_flag(self, name, filters):
        feature_flag_key = slugify(f"survey-targeting-{name}")
        feature_flag_serializer = FeatureFlagSerializer(
            data={
                "key": feature_flag_key,
                "name": f"Targeting flag for survey {name}",
                "filters": filters,
            },
            context=self.context,
        )

        feature_flag_serializer.is_valid(raise_exception=True)
        targeting_feature_flag = feature_flag_serializer.save()
        return targeting_feature_flag


class SurveyViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = Survey.objects.select_related("linked_flag", "targeting_flag").all()
    permission_classes = [
        IsAuthenticated,
        ProjectMembershipNecessaryPermissions,
        TeamMemberAccessPermission,
    ]

    def get_serializer_class(self) -> Type[serializers.Serializer]:
        if self.request.method == "POST" or self.request.method == "PATCH":
            return SurveySerializerCreateUpdateOnly
        else:
            return SurveySerializer

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        related_targeting_flag = instance.targeting_flag
        if related_targeting_flag:
            related_targeting_flag.delete()

        return super().destroy(request, *args, **kwargs)
