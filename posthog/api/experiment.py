import json
from typing import Any
from django.http import HttpResponse, JsonResponse
from rest_framework import status, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import get_token
from django.views.decorators.csrf import csrf_exempt
from posthog.auth import (
    TemporaryTokenAuthentication,
)
from posthog.exceptions import generate_exception_response
from posthog.models import Team, Experiment, WebExperiment
from posthog.utils_cors import cors_response



class ExperimentTransformSerializer(serializers.Serializer):
    transforms = serializers.SerializerMethodField()
    rollout_percentage = serializers.SerializerMethodField()

    class Meta:
        fields = ["transforms", "rollout_percentage"]
        # read_only_fields = fields

    def get_transforms(self, instance):
        if instance is None or instance.get('data', None) is None:
            return

        return json.loads(instance.get('data', {})).get("data", {})

    def get_rollout_percentage(self, instance):
        if instance is None or instance.get('rollout_percentage', None) is None:
            return
        return instance.get('rollout_percentage', 0)


class ExperimentsAPISerializer(serializers.ModelSerializer):
    """
    Serializer for the exposed /api/experiments endpoint, to be used in posthog-js and for headless APIs.
    """

    variants = serializers.JSONField(read_only=False)
    feature_flag_key = serializers.CharField(source="feature_flag.key", read_only=True)

    class Meta:
        model = WebExperiment
        fields = ["id", "name", "feature_flag_key", "variants"]
        # read_only_fields = fields

    # def get_variants(self, experiment: Experiment):
    #     if experiment.feature_flag is None:
    #         return
    #     #
    #     if experiment.feature_flag.filters is None:
    #         return
    #
    #     multivariate = experiment.feature_flag.filters.get("multivariate", None)
    #     if multivariate is None:
    #         return
    #
    #     variants = multivariate.get("variants", [])
    #     if len(variants) == 0:
    #         return
    #
    #     payloads = experiment.feature_flag.filters.get("payloads", {})
    #     if len(payloads) == 0:
    #         return
    #
    #     if not isinstance(payloads, dict):
    #         return
    #
    #     for variant in variants:
    #         rollout_percentage = variant.get("rollout_percentage",0)
    #         key = variant.get("key", None)
    #         # print('variant is ', key, '  rollout_percentage is ', rollout_percentage, '  payload is ', payloads)
    #         serializer_payload = {
    #             'data': payloads.get(key, None),
    #             'rollout_percentage': rollout_percentage
    #         }
    #         variant_transforms_payload = ExperimentTransformSerializer(serializer_payload)
    #         # variant_transforms_payload.rollout_percentage = rollout_percentage
    #         payloads[key] = variant_transforms_payload.data
    #         # payloads[key].
    #         payloads[key].rollout_percentage = rollout_percentage
    #     return payloads

    def validate(self, attrs):
        print('input to REST API is ', attrs)
        return attrs

    def update(self, instance: WebExperiment, validated_data: dict[str, Any]) -> Any:
        print("updating instance, validated_data is ", validated_data, " instance is ", instance)
        variants = validated_data.pop("variants", None)
        if variants is not None and isinstance(variants, dict):
            feature_flag = instance.feature_flag

            filters = {
                'groups': feature_flag.filters.get('groups', None),
                'payloads': {},
                'multivariate': feature_flag.filters.get('multivariate', None),
            }
            for variant, transforms in variants.items():
                filters['payloads'][variant] = json.dumps({"data": transforms.get("transforms", {})})

            print('filter payloads is ', filters)
            validated_data["filters"] = filters
            super().update(feature_flag, validated_data)

        instance = super().update(instance, validated_data)
        return instance

class ExperimentViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment"
    serializer_class = ExperimentsAPISerializer
    authentication_classes = [TemporaryTokenAuthentication]
    queryset = WebExperiment.objects.select_related("feature_flag").all()

@action(methods=["PATCH"], detail=True)
def update_experiments(request: Request):
    print('request is not supported')
    return cors_response(
        request,
        generate_exception_response(
            "experiments",
            "Not Supported.",
            type="authentication_error",
            code="missing_api_key",
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        ),
    )

@csrf_exempt
@action(methods=["GET"], detail=True)
def experiments(request: Request):
    token = get_token(None, request)
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))
    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "experiments",
                "API key not provided. You can find your project API key in your PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    if request.method == "GET":
        team = Team.objects.get_team_from_cache_or_token(token)
        if team is None:
            return cors_response(
                request,
                generate_exception_response(
                    "experiments",
                    "Project API key invalid. You can find your project API key in your PostHog project settings.",
                    type="authentication_error",
                    code="invalid_api_key",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )

        result = ExperimentsAPISerializer(
            WebExperiment.objects.filter(team_id=team.id).exclude(archived=True).select_related("feature_flag"),
            many=True,
        ).data

        return cors_response(request, JsonResponse({"experiments": result}))

