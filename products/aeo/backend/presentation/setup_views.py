from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.rate_limit import AEOSetupBurstRateThrottle, AEOSetupSustainedRateThrottle

from products.aeo.backend.facade.api import get_setup, get_setup_context, start_setup
from products.aeo.backend.facade.contracts import (
    MAX_SETUP_WEBSITES,
    SETUP_ENOUGH_KEYWORDS,
    SETUP_ENOUGH_PROMPTS,
    SETUP_KEYWORD_COUNT,
    SETUP_PROMPT_COUNT,
    SETUP_WEBSITE_DAYS,
    SetupAlreadyRunningError,
    SetupContext,
    SetupJob,
    SetupJobNotFoundError,
    SetupRequest,
    SetupRequestError,
    SetupStepState,
    WebsiteCandidate,
)
from products.aeo.backend.presentation.views import AEOEngineSettingSerializer, _AEOFlagGateMixin

SETUP_DESCRIPTION = (
    "Sets up AI visibility tracking for the project in one job. Requires AI data processing approved for the "
    "organization. In order, it adds the site as the project's own brand, has PostHog suggest "
    f"{SETUP_PROMPT_COUNT} prompts and saves them, and has PostHog suggest {SETUP_KEYWORD_COUNT} keywords and saves "
    "them. With run_first_check the prompts are saved active and a first citation check run is queued with the "
    "enabled engines; each check is a paid call to every enabled engine, and each engine keeps checking active "
    "prompts on its schedule. Without it, new prompts are saved paused, so nothing is checked or spent until they "
    "are turned on. A step the project already covers is skipped: an own brand exists, "
    f"{SETUP_ENOUGH_PROMPTS} or more unarchived prompts, {SETUP_ENOUGH_KEYWORDS} or more keywords, or any check "
    "already recorded. With engines, the chosen engines are turned on and every other one off before the "
    "job starts. Returns a pending job right away; poll GET aeo_setup/<id>/ until it completes, which takes a few "
    "minutes. Running it again only fills the gaps."
)


class AEOWebsiteCandidateSerializer(DataclassSerializer):
    class Meta:
        dataclass = WebsiteCandidate
        ref_name = "AEOWebsiteCandidate"
        extra_kwargs = {
            "domain": {"help_text": "A registrable domain the project may be about, for example example.com."},
            "source": {
                "help_text": "Where PostHog found it: own_brand (an own brand in the catalog), app_urls (the "
                "project's authorized URLs), recording_domains (the domains allowed to record sessions) or "
                f"pageviews (hosts with pageviews in the last {SETUP_WEBSITE_DAYS} days)."
            },
            "pageviews": {
                "help_text": f"Pageviews on the domain in the last {SETUP_WEBSITE_DAYS} days. Null unless source is pageviews."
            },
        }


class AEOSetupContextSerializer(DataclassSerializer):
    websites = AEOWebsiteCandidateSerializer(
        many=True,
        help_text=f"Up to {MAX_SETUP_WEBSITES} domains the project may be about, the most likely first.",
    )
    engines = AEOEngineSettingSerializer(
        many=True,
        help_text="Every engine as the project runs it now, defaults included. Ask the user which ones to track, "
        "and offer only the available ones.",
    )

    class Meta:
        dataclass = SetupContext
        ref_name = "AEOSetupContext"
        extra_kwargs = {
            "own_domains": {"help_text": "Domains already set as the project's own brands."},
            "active_prompts": {"help_text": "Active, unarchived prompts the project tracks."},
            "paused_prompts": {"help_text": "Unarchived prompts that are turned off. No run checks them."},
            "keywords": {"help_text": "Keywords in the project's keyword list."},
            "has_checks": {"help_text": "Whether any citation check has been recorded for the project."},
            "ai_data_processing_approved": {
                "help_text": "Whether the organization approved AI data processing. Setup needs it."
            },
            "first_run_available": {
                "help_text": "Whether citation checks run for this project. When false, setup saves the brand, "
                "prompts and keywords but cannot queue the first run."
            },
            "website_days": {"help_text": "The window, in days, that pageview hosts among the websites cover."},
            "prompt_target": {
                "help_text": "How many prompts setup asks PostHog to suggest. One run makes about this many checks "
                "per enabled engine."
            },
        }


class AEOSetupRequestSerializer(serializers.Serializer):
    domain = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="The project's site, for example example.com. It becomes the own brand, and PostHog reads it to "
        "suggest prompts and keywords. Required unless only_first_run is true.",
    )
    brand = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="The brand name. Inferred from the site when empty.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="What the product does and who it is for. Inferred from the site when empty.",
    )
    engines = serializers.ListField(
        child=serializers.CharField(max_length=64, help_text="An engine id from GET aeo_setup/context/."),
        required=False,
        max_length=20,
        help_text="The engines to track, by id. Every other engine is turned off before any run. An engine that is "
        "not available yet may be chosen: it stays on and PostHog starts checking with it once it is available. "
        "Leave it out to keep the current engine settings.",
    )
    run_first_check = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Queue a first citation check run after setup. Each check is a paid call to every enabled engine. "
        "When false, setup saves the new prompts paused, so no checks run and nothing is spent until they are turned "
        "on, for example with only_first_run and activate_paused_prompts.",
    )
    only_first_run = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Queue a citation check run and nothing else: no brand, prompts or keywords, and no engine change. "
        "Use it when the project is already set up and should be checked now instead of on its schedule. Each "
        "check is a paid call to every enabled engine.",
    )

    activate_paused_prompts = serializers.BooleanField(
        required=False,
        default=False,
        help_text="With only_first_run, turn on every paused prompt before the run, such as the ones a setup without "
        "run_first_check saved paused. Turned-on prompts are checked on each engine's schedule from then on.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("activate_paused_prompts") and not attrs.get("only_first_run"):
            raise serializers.ValidationError({"activate_paused_prompts": "Only valid together with only_first_run."})
        if attrs.get("only_first_run"):
            if "engines" in attrs:
                raise serializers.ValidationError({"engines": "Leave engines out when only_first_run is true."})
        elif not attrs.get("domain", "").strip():
            raise serializers.ValidationError({"domain": "Enter the project's site."})
        return attrs


class AEOSetupConflictSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the request was refused.")
    job_id = serializers.CharField(help_text="The setup job already running. Poll GET aeo_setup/<id>/ with it.")


class AEOSetupStepSerializer(DataclassSerializer):
    class Meta:
        dataclass = SetupStepState
        ref_name = "AEOSetupStep"
        extra_kwargs = {
            "step": {
                "help_text": "brand (the own brand), prompts (suggested and saved), keywords (suggested and saved) or first_run (the first citation check run queued)."
            },
            "status": {
                "help_text": "pending, running, done, skipped (the project already had it, or the first run was not requested or is not available) or failed."
            },
            "added": {"help_text": "How many brands, prompts or keywords the step added."},
            "detail": {
                "help_text": "Why a step was skipped (already_set, already_run, not_requested, not_available, nothing_to_run), why the keywords or first_run step failed, or 'paused' when the prompts step saved its prompts turned off."
            },
        }


class AEOSetupJobSerializer(DataclassSerializer):
    steps = AEOSetupStepSerializer(many=True, help_text="The setup steps in the order they run.")

    class Meta:
        dataclass = SetupJob
        ref_name = "AEOSetupJob"
        extra_kwargs = {
            "id": {"help_text": "Job id. Poll GET aeo_setup/<id>/ with it."},
            "status": {
                "help_text": "pending while PostHog works, then completed or failed. A failed keywords step does not fail the job."
            },
            "error": {"help_text": "Why the job failed. Empty unless status is failed."},
        }


class AEOSetupViewSet(_AEOFlagGateMixin, viewsets.GenericViewSet):
    scope_object = "web_analytics"
    scope_object_read_actions = ["context", "retrieve"]
    # Setup saves a brand, prompts and keywords and spends model credits, so it needs write access.
    scope_object_write_actions = ["create"]
    pagination_class = None
    lookup_value_regex = r"[0-9a-f-]{36}"

    @validated_request(
        operation_id="aeo_setup_context",
        summary="Get AEO setup context",
        description=(
            "Gets what PostHog already knows about the project for AI visibility setup: the domains it may be about, "
            "from its own brands, authorized URLs, recording domains and pageview hosts, and how many prompts, "
            "keywords and checks it has. Use the first website as the default domain for POST aeo_setup/."
        ),
        responses={200: OpenApiResponse(response=AEOSetupContextSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["get"])
    def context(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        return Response(AEOSetupContextSerializer(get_setup_context(self.team_id)).data)

    @validated_request(
        request_serializer=AEOSetupRequestSerializer,
        operation_id="aeo_setup_create",
        summary="Set up AI visibility",
        description=SETUP_DESCRIPTION,
        responses={
            202: OpenApiResponse(response=AEOSetupJobSerializer),
            400: OpenApiResponse(description="The domain is not valid, or no chosen engine can run."),
            409: OpenApiResponse(
                response=AEOSetupConflictSerializer, description="A setup job is already running for the project."
            ),
        },
        tags=["web_analytics"],
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        data = request.validated_data
        # The site, prompts and keywords go to a model, so the organization must have approved AI data processing.
        # A run-only request sends nothing to a model beyond the checks themselves.
        if not data["only_first_run"] and not self.organization.is_ai_data_processing_approved:
            raise PermissionDenied(
                "Setup needs AI data processing approved for your organization. An admin can approve it in organization settings."
            )
        try:
            job = start_setup(
                self.team_id,
                SetupRequest(
                    domain=data.get("domain", ""),
                    brand=data.get("brand", ""),
                    description=data.get("description", ""),
                    run_first_check=data["run_first_check"],
                    engines=tuple(data["engines"]) if "engines" in data else None,
                    only_first_run=data["only_first_run"],
                    activate_paused_prompts=data["activate_paused_prompts"],
                ),
            )
        except SetupRequestError as error:
            raise ValidationError(str(error))
        except SetupAlreadyRunningError as error:
            return Response(
                AEOSetupConflictSerializer(
                    {"detail": "Setup is already running for this project.", "job_id": error.job_id}
                ).data,
                status=status.HTTP_409_CONFLICT,
            )
        return Response(AEOSetupJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @validated_request(
        operation_id="aeo_setup_retrieve",
        summary="Get AEO setup job",
        description="Gets a setup job started with POST aeo_setup/, with the state of each step. Jobs expire an hour after their last update.",
        responses={200: OpenApiResponse(response=AEOSetupJobSerializer)},
        tags=["web_analytics"],
    )
    def retrieve(self, request: ValidatedRequest, pk: str, **kwargs: Any) -> Response:
        try:
            job = get_setup(self.team_id, pk)
        except SetupJobNotFoundError:
            raise NotFound()
        return Response(AEOSetupJobSerializer(job).data)

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "create":
            return [AEOSetupBurstRateThrottle(), AEOSetupSustainedRateThrottle()]
        return list(super().get_throttles())
