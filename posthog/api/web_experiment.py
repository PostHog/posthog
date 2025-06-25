from typing import Any

from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from nanoid import generate
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import get_token
from posthog.auth import (
    TemporaryTokenAuthentication,
)
from posthog.exceptions import generate_exception_response
from posthog.models import Team, WebExperiment
from posthog.utils_cors import cors_response


class WebExperimentsAPISerializer(serializers.ModelSerializer):
    """
    Serializer for the exposed /api/web_experiments endpoint, to be used in posthog-js and for headless APIs.
    """

    feature_flag_key = serializers.CharField(source="feature_flag.key", read_only=True)

    class Meta:
        model = WebExperiment
        fields = ["id", "name", "created_at", "feature_flag_key", "variants"]

    # Validates that the `variants` property in the request follows this known object format.
    # {
    #     "name": "create-params-debug",
    #     "variants": {
    #         "control": {
    #             "transforms": [
    #                 {
    #                     "text": "Here comes Superman!",
    #                     "html": "",
    #                     "selector": "#page > #body > .header h1"
    #                 }
    #             ],
    #             "conditions": "None",
    #             "rollout_percentage": 50
    #         },
    #     }
    # }
    def validate(self, attrs):
        variants = attrs.get("variants")
        if variants is None:
            raise ValidationError("Experiment does not have any variants")
        if variants and not isinstance(variants, dict):
            raise ValidationError("Experiment variants should be a dictionary of keys -> transforms")
        if "control" not in variants:
            raise ValidationError("Experiment should contain a control variant")
        for name, variant in variants.items():
            if variant.get("rollout_percentage") is None:
                raise ValidationError(f"Experiment variant '{name}' does not have any rollout percentage")
            if name != "control":
                transforms = variant.get("transforms", {})
                for idx, transform in enumerate(transforms):
                    if transform.get("selector") is None:
                        raise ValidationError(
                            f"Experiment transform [${idx}] variant '{name}' does not have a valid selector"
                        )

        return attrs

    def create(self, validated_data: dict[str, Any]) -> WebExperiment:
        create_params = {
            "name": validated_data.get("name", ""),
            "description": "",
            "type": "web",
            "created_by": self.context["request"].user,
            "variants": validated_data.get("variants", None),
        }

        filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": self.get_variants_for_feature_flag(validated_data),
        }

        feature_flag_serializer = FeatureFlagSerializer(
            data={
                "key": self.get_feature_flag_name(validated_data.get("name", "")),
                "name": f"Feature Flag for Experiment {validated_data['name']}",
                "filters": filters,
                "active": False,
                "creation_context": "web_experiments",
            },
            context=self.context,
        )

        feature_flag_serializer.is_valid(raise_exception=True)
        feature_flag = feature_flag_serializer.save()

        # Get organization's default stats method setting
        team = Team.objects.get(id=self.context["team_id"])
        default_method = team.organization.default_experiment_stats_method
        stats_config = {
            "method": default_method,
        }

        experiment = WebExperiment.objects.create(
            team_id=self.context["team_id"], feature_flag=feature_flag, **create_params, stats_config=stats_config
        )
        return experiment

    def update(self, instance: WebExperiment, validated_data: dict[str, Any]) -> WebExperiment:
        variants = validated_data.get("variants", None)
        if variants is not None and isinstance(variants, dict):
            feature_flag = instance.feature_flag
            filters = {
                "groups": feature_flag.filters.get("groups", None),
                "multivariate": self.get_variants_for_feature_flag(validated_data),
            }

            existing_flag_serializer = FeatureFlagSerializer(
                feature_flag,
                data={"filters": filters},
                partial=True,
                context=self.context,
            )
            existing_flag_serializer.is_valid(raise_exception=True)
            existing_flag_serializer.save()

        instance = super().update(instance, validated_data)
        return instance

    def get_variants_for_feature_flag(self, validated_data: dict[str, Any]):
        variant_names = []
        variants = validated_data.get("variants", None)
        if variants is not None and isinstance(variants, dict):
            for variant, transforms in variants.items():
                variant_names.append({"key": variant, "rollout_percentage": transforms.get("rollout_percentage", 0)})
        return {"variants": variant_names}

    def get_feature_flag_name(self, experiment_name: str) -> str:
        random_id = generate("1234567890abcdef", 10)
        prefix = experiment_name.replace(" ", "-").lower() + "-web-experiment-feature"
        feature_flag_key = slugify(f"{prefix}-{random_id}")
        return feature_flag_key


class WebExperimentViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment"
    serializer_class = WebExperimentsAPISerializer
    authentication_classes = [TemporaryTokenAuthentication]
    queryset = (
        WebExperiment.objects.select_related("feature_flag", "created_by")
        .exclude(deleted=True)
        .order_by("-created_at")
        .all()
    )


@csrf_exempt
@action(methods=["GET"], detail=True)
def web_experiments(request: Request):
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

        result = WebExperimentsAPISerializer(
            WebExperiment.objects.filter(team_id=team.id)
            .exclude(archived=True)
            .exclude(deleted=True)
            .exclude(end_date__isnull=False)
            .select_related("feature_flag", "created_by")
            .order_by("-created_at"),
            many=True,
        ).data

        return cors_response(request, JsonResponse({"experiments": result}))
