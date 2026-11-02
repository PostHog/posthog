import re
from html.parser import HTMLParser
from typing import Any

from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

from nanoid import generate
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import get_token
from posthog.event_usage import report_user_action
from posthog.exceptions import generate_exception_response
from posthog.models import Team
from posthog.utils_cors import cors_response

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.web_experiment import WebExperiment
from products.feature_flags.backend.facade.api import create_flag, update_flag
from products.feature_flags.backend.facade.filters import replace_variant_distribution

_DISALLOWED_TAG_MESSAGES: dict[str, str] = {
    "script": "contains disallowed <script> tags",
    "iframe": "contains disallowed <iframe> tags",
    "object": "contains disallowed <object> or <embed> tags",
    "embed": "contains disallowed <object> or <embed> tags",
}
_EVENT_HANDLER_MESSAGE = "contains disallowed event handlers (onclick, onerror, etc.)"
_JAVASCRIPT_URL_MESSAGE = "contains disallowed javascript: protocol"
_VBSCRIPT_URL_MESSAGE = "contains disallowed vbscript: protocol"
_DATA_HTML_URL_MESSAGE = "contains disallowed data:text/html"
_NESTING_MESSAGE = "contains markup nested too deeply to check"
_MAX_NESTED_CHECKS = 8

# Browsers ignore whitespace and control characters in a URL scheme; ";" and "," split SVG "values" lists.
_URL_CONTROL_CHARS = re.compile(r"[\x00-\x20]+")
_JAVASCRIPT_URL = re.compile(r"(?:^|[;,])javascript:")
_VBSCRIPT_URL = re.compile(r"(?:^|[;,])vbscript:")
_DATA_HTML_URL = re.compile(r"(?:^|[;,])data:text/html")


class _UnsafeHTMLFinder(HTMLParser):
    """
    Finds markup that runs script when posthog-js writes a transform into the page with innerHTML.

    The finder parses the markup instead of matching the raw string, so that entity encoding,
    letter case and attribute separators do not hide a handler or a URL scheme.
    """

    def __init__(self, depth: int = 0) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = depth
        self.problem: str | None = None

    def set_cdata_mode(self, *args: Any, **kwargs: Any) -> None:
        # Read <script> and <style> bodies as markup, because a browser does so inside <svg>.
        return

    def _report(self, message: str) -> None:
        if self.problem is None:
            self.problem = message

    def _check_nested(self, content: str) -> None:
        # A browser can end a raw-text element such as <style> inside a comment or an attribute
        # value and parse the rest as markup, so the raw source of comments and tags is checked too.
        if "<" not in content:
            return
        if self.depth >= _MAX_NESTED_CHECKS:
            self._report(_NESTING_MESSAGE)
            return
        nested = find_unsafe_html(content, self.depth + 1)
        if nested:
            self._report(nested)

    def _check_tag(self, tag: str) -> None:
        message = _DISALLOWED_TAG_MESSAGES.get(tag)
        if message:
            self._report(message)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag)
        for name, value in attrs:
            if name.startswith("on"):
                self._report(_EVENT_HANDLER_MESSAGE)
            if value is None:
                continue
            url = _URL_CONTROL_CHARS.sub("", value).lower()
            if _JAVASCRIPT_URL.search(url):
                self._report(_JAVASCRIPT_URL_MESSAGE)
            elif _VBSCRIPT_URL.search(url):
                self._report(_VBSCRIPT_URL_MESSAGE)
            elif _DATA_HTML_URL.search(url):
                self._report(_DATA_HTML_URL_MESSAGE)
        raw_tag = self.get_starttag_text()
        if raw_tag:
            self._check_nested(raw_tag[1:])

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._report("contains disallowed </script> tags")

    def handle_comment(self, data: str) -> None:
        self._check_nested(data)

    def handle_decl(self, decl: str) -> None:
        self._check_nested(decl)

    def unknown_decl(self, data: str) -> None:
        self._check_nested(data)

    def handle_pi(self, data: str) -> None:
        self._check_nested(data)


def find_unsafe_html(content: str, depth: int = 0) -> str | None:
    finder = _UnsafeHTMLFinder(depth)
    finder.feed(content)
    finder.close()
    return finder.problem


def validate_no_xss(content: str, field_name: str) -> None:
    """
    Raises ValidationError if the content contains markup that can run script.

    The check rejects the content and does not change it, so valid content keeps its original formatting.
    """
    problem = find_unsafe_html(content)
    if problem:
        raise ValidationError(f"{field_name} {problem}")


class WebExperimentsAPISerializer(serializers.ModelSerializer):
    """
    Serializer for the exposed /api/web_experiments endpoint, to be used in posthog-js and for headless APIs.
    """

    feature_flag_key = serializers.CharField(source="feature_flag.key", read_only=True)

    variants = serializers.JSONField(
        help_text="""Variants for the web experiment. Example:

        {
            "control": {
                "transforms": [
                    {
                        "text": "Here comes Superman!",
                        "html": "",
                        "selector": "#page > #body > .header h1"
                    }
                ],
                "conditions": "None",
                "rollout_percentage": 50
            },
        }""",
    )

    class Meta:
        model = WebExperiment
        fields = ["id", "name", "created_at", "feature_flag_key", "variants"]

    def to_representation(self, instance):
        """
        Override to return variants with actual rollout percentages from the feature flag.
        """
        data = super().to_representation(instance)

        # Get corrected variants with actual feature flag rollout percentages
        data["variants"] = self._get_corrected_variants(instance)

        return data

    def _get_corrected_variants(self, obj):
        """
        Returns ALL variants from the feature flag with actual rollout percentages,
        combined with transforms from the experiment variants where available.
        """
        if not obj.feature_flag:
            return obj.variants or {}

        variants_list = obj.feature_flag.variants

        # If no feature flag variants, fall back to experiment variants
        if not variants_list:
            return obj.variants or {}

        # Build result using ALL feature flag variants as the source of truth
        result_variants = {}
        experiment_variants = obj.variants or {}

        for variant in variants_list:
            key = variant.get("key")
            rollout_percentage = variant.get("rollout_percentage", 0)
            if key:
                # Start with feature flag data
                result_variants[key] = {"rollout_percentage": rollout_percentage}

                # Add experiment-specific data (transforms, etc.) if available
                if key in experiment_variants:
                    experiment_data = experiment_variants[key].copy()
                    # Remove rollout_percentage from experiment data to avoid conflicts
                    experiment_data.pop("rollout_percentage", None)
                    # Merge experiment data into result
                    result_variants[key].update(experiment_data)

        return result_variants

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

                    # Validate text and html fields to prevent XSS attacks
                    if "text" in transform and isinstance(transform["text"], str):
                        validate_no_xss(transform["text"], f"Transform text in variant '{name}'")
                    if "html" in transform and isinstance(transform["html"], str):
                        validate_no_xss(transform["html"], f"Transform html in variant '{name}'")

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

        team = self.context["get_team"]()
        feature_flag = create_flag(
            {
                "key": self.get_feature_flag_name(validated_data.get("name", "")),
                "name": f"Feature Flag for Experiment {validated_data['name']}",
                "filters": filters,
                "active": False,
                "creation_context": "web_experiments",
            },
            team=team,
            user=self.context["request"].user,
            request=self.context["request"],
        )

        # Get team's default stats method setting
        from posthog.models.team.extensions import get_or_create_team_extension

        from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

        config = get_or_create_team_extension(team, TeamExperimentsConfig)
        default_method = config.default_experiment_stats_method or "bayesian"
        stats_config = {
            "method": default_method,
        }

        experiment = WebExperiment.objects.create(
            team_id=self.context["team_id"], feature_flag=feature_flag, **create_params, stats_config=stats_config
        )

        report_user_action(
            self.context["request"].user,
            "experiment created",
            {**experiment.get_analytics_metadata(), "creation_mode": "new"},
            team=team,
            request=self.context["request"],
        )

        return experiment

    def update(self, instance: WebExperiment, validated_data: dict[str, Any]) -> WebExperiment:
        variants = validated_data.get("variants", None)
        if variants is not None and isinstance(variants, dict):
            feature_flag = instance.feature_flag
            filters = replace_variant_distribution(
                feature_flag.get_filters(),
                self.get_variants_for_feature_flag(validated_data)["variants"],
            )
            update_flag(
                feature_flag,
                {"filters": filters},
                team=self.context["get_team"](),
                user=self.context["request"].user,
                request=self.context["request"],
            )

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
    queryset = WebExperiment.objects.select_related("feature_flag", "created_by").order_by("-created_at", "-id").all()

    def safely_get_queryset(self, queryset):
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
        return queryset


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
                "Project token not provided. You can find your project token in your PostHog project settings.",
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
                    "Project token invalid. You can find your project token in your PostHog project settings.",
                    type="authentication_error",
                    code="invalid_api_key",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )

        result = WebExperimentsAPISerializer(
            WebExperiment.objects.filter(team_id=team.id)
            .exclude(archived=True)
            .exclude(deleted=True)
            .filter(status__in=[Experiment.Status.DRAFT, Experiment.Status.RUNNING])
            .select_related("feature_flag", "created_by")
            .order_by("-created_at"),
            many=True,
        ).data

        return cors_response(request, JsonResponse({"experiments": result}))
