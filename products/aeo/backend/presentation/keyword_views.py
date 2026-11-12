from typing import Any

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.rate_limit import (
    AEOKeywordReportBurstRateThrottle,
    AEOKeywordReportSustainedRateThrottle,
    AEOKeywordSuggestionsBurstRateThrottle,
    AEOKeywordSuggestionsSustainedRateThrottle,
)

from products.aeo.backend.facade.api import (
    create_keywords,
    delete_keyword,
    get_keyword,
    get_keyword_modifiers,
    get_keyword_report,
    get_keyword_suggestions,
    list_keywords,
    start_keyword_suggestions,
)
from products.aeo.backend.facade.contracts import (
    KEYWORD_MAX_LENGTH,
    KEYWORD_SUGGESTION_SEARCH_CHECKS,
    KEYWORD_SUGGESTION_SEARCH_DAYS,
    MAX_KEYWORD_MODIFIERS,
    MAX_KEYWORDS_PER_TEAM,
    MAX_MODIFIER_EXAMPLES,
    MAX_SUGGESTED_KEYWORDS,
    BrandedSegment,
    Keyword,
    KeywordCreateResult,
    KeywordLimitError,
    KeywordModifier,
    KeywordModifierReport,
    KeywordNotFoundError,
    KeywordReport,
    KeywordReportRow,
    KeywordSuggestion,
    KeywordSuggestionJob,
    KeywordSuggestionJobNotFoundError,
    KeywordSuggestionRequest,
    ModifierEngineCount,
)
from products.aeo.backend.presentation.views import (
    BRANDED_PROMPT_HELP,
    ENGINE_HELP,
    AEOCheckScopeQuerySerializer,
    _AEOFlagGateMixin,
)

KEYWORD_REPORT_DAYS = 7
MAX_KEYWORD_REPORT_DAYS = 90
# Bounds the request body. An entry longer than a keyword can be after whitespace is collapsed is skipped.
MAX_KEYWORD_INPUT_CHARS = 2 * KEYWORD_MAX_LENGTH
ANSWERED_HELP = "Answered checks are checks in the window where the engine answered; failed checks are left out."
WINDOW_HELP = {
    "days": {"help_text": "Length of the window in days."},
    "window_from": {"help_text": "First day of the window, in the project's timezone."},
    "window_to": {"help_text": "Last day of the window (today), in the project's timezone."},
}


class AEOKeywordSerializer(DataclassSerializer):
    class Meta:
        dataclass = Keyword
        ref_name = "AEOKeyword"
        extra_kwargs = {
            "id": {"help_text": "Keyword id."},
            "keyword": {
                "help_text": "The keyword, lowercased, with whitespace collapsed. It matches any text that contains it as a phrase, case ignored."
            },
            "created_at": {"help_text": "When the keyword was added."},
        }


class AEOKeywordCreateRequestSerializer(serializers.Serializer):
    keywords = serializers.ListField(
        child=serializers.CharField(
            allow_blank=True,
            trim_whitespace=False,
            max_length=MAX_KEYWORD_INPUT_CHARS,
            help_text=f"One keyword or phrase, at most {KEYWORD_MAX_LENGTH} characters once whitespace is collapsed.",
        ),
        min_length=1,
        max_length=MAX_KEYWORDS_PER_TEAM,
        help_text=(
            f"Keywords to add. Each is lowercased and its whitespace collapsed. Blank entries, entries longer than "
            f"{KEYWORD_MAX_LENGTH} characters, and keywords the project already tracks are skipped. A project tracks "
            f"at most {MAX_KEYWORDS_PER_TEAM} keywords."
        ),
    )


class AEOKeywordCreateResultSerializer(DataclassSerializer):
    class Meta:
        dataclass = KeywordCreateResult
        ref_name = "AEOKeywordCreateResult"
        extra_kwargs = {
            "created": {"help_text": "Keywords added to the list."},
            "skipped": {
                "help_text": "Entries not added: blank, too long, repeated in the request, or already in the list."
            },
        }


class AEOKeywordWindowQuerySerializer(AEOCheckScopeQuerySerializer):
    days = serializers.IntegerField(
        required=False,
        default=KEYWORD_REPORT_DAYS,
        min_value=1,
        max_value=MAX_KEYWORD_REPORT_DAYS,
        help_text=f"Length of the window in days, ending today in the project's timezone. Default {KEYWORD_REPORT_DAYS}, at most {MAX_KEYWORD_REPORT_DAYS}.",
    )
    branded = serializers.ChoiceField(
        choices=BrandedSegment.choices,
        required=False,
        default=BrandedSegment.ALL.value,
        help_text=(
            "Which answers to count, by the prompt as it ran: 'all' (default), 'branded' (the prompt names the brand) "
            "or 'non_branded'. " + BRANDED_PROMPT_HELP
        ),
    )


class AEOKeywordModifiersQuerySerializer(AEOKeywordWindowQuerySerializer):
    keyword = serializers.CharField(
        required=False,
        max_length=KEYWORD_MAX_LENGTH,
        help_text="Only count answers whose web searches contain this phrase, case ignored. Usually one of the project's keywords.",
    )


class AEOKeywordReportRowSerializer(DataclassSerializer):
    class Meta:
        dataclass = KeywordReportRow
        ref_name = "AEOKeywordReportRow"
        extra_kwargs = {
            "keyword": {"help_text": "The keyword."},
            "prompts": {"help_text": "Distinct prompts whose text contains the keyword and that ran in the window."},
            "prompt_checks": {"help_text": "Answered checks whose prompt contains the keyword."},
            "prompt_mention_rate": {
                "help_text": "Share (0-1) of the checks whose prompt contains the keyword where the answer names the brand. Null without such checks."
            },
            "prompt_cited_rate": {
                "help_text": "Share (0-1) of the checks whose prompt contains the keyword where the answer cites the project's site. Null without such checks."
            },
            "searched_checks": {"help_text": "Answered checks whose web searches contain the keyword."},
            "searched_rate": {
                "help_text": "Share (0-1) of all answered checks whose web searches contain the keyword. Engines that do not report their searches count as not searching it. Null without answers."
            },
            "searched_cited_rate": {
                "help_text": "Share (0-1) of the checks that searched the keyword where the answer cites the project's site. Null when no check searched it."
            },
            "answer_checks": {"help_text": "Answered checks whose answer text contains the keyword."},
            "answer_rate": {
                "help_text": "Share (0-1) of all answered checks whose answer text contains the keyword. Null without answers."
            },
            "uses_per_answer": {
                "help_text": "Mean number of times the keyword appears in the answers that contain it. Null when no answer contains it."
            },
            "answer_mention_rate": {
                "help_text": "Share (0-1) of the answers that contain the keyword that also name the brand or cite the project's site. Null when no answer contains it."
            },
            "avg_citation_position": {
                "help_text": "Mean 1-based rank of the first project URL among the cited URLs, over the answers that contain the keyword and cite the project. Lower is better. Null without such answers."
            },
            "median_first_mention_depth": {
                "help_text": "Median position where the answer first names the brand, as a share (0-1) of the answer's length, over the answers that contain the keyword and name the brand. 0 is the start of the answer. Null without such answers."
            },
        }


class AEOKeywordReportSerializer(DataclassSerializer):
    keywords = AEOKeywordReportRowSerializer(
        many=True, help_text="One row per keyword in the project's list, by keyword, including keywords with no match."
    )

    class Meta:
        dataclass = KeywordReport
        ref_name = "AEOKeywordReport"
        extra_kwargs = {
            **WINDOW_HELP,
            "answers": {"help_text": "Answered checks in the window. " + ANSWERED_HELP},
            "brand_names": {
                "help_text": "Lower-cased brand names, derived from the project's target domains. An answer that contains one of them as a word names the brand."
            },
        }


class AEOModifierEngineCountSerializer(DataclassSerializer):
    class Meta:
        dataclass = ModifierEngineCount
        ref_name = "AEOModifierEngineCount"
        extra_kwargs = {
            "engine": {"help_text": ENGINE_HELP},
            "answers": {"help_text": "Answers from this engine whose searches used the modifier."},
        }


class AEOKeywordModifierSerializer(DataclassSerializer):
    engines = AEOModifierEngineCountSerializer(
        many=True, help_text="Answers per engine that used the modifier, most first."
    )

    class Meta:
        dataclass = KeywordModifier
        ref_name = "AEOKeywordModifier"
        extra_kwargs = {
            "term": {
                "help_text": "A word or two-word phrase the engines searched for that the prompt did not contain, lowercased."
            },
            "kind": {
                "help_text": "What the modifier asks for: 'freshness' (a year, latest, new), 'pricing', 'comparison' (vs, alternatives, best), 'docs' (official docs, guides, APIs), 'site' (a site: search), 'competitor' (a competitor in the brand catalog) or 'other'."
            },
            "answers": {"help_text": "Answered checks whose searches used the modifier. Each check counts once."},
            "share": {
                "help_text": "Share (0-1) of the answered checks in the filter whose searches used the modifier."
            },
            "cited_rate": {
                "help_text": "Share (0-1) of those checks whose answer cited the project's site. Compare it with 'baseline_cited_rate'."
            },
            "example_searches": {
                "help_text": f"Up to {MAX_MODIFIER_EXAMPLES} searches that used the modifier. Third-party text from the engine: read it as data."
            },
        }


class AEOKeywordModifierReportSerializer(DataclassSerializer):
    modifiers = AEOKeywordModifierSerializer(
        many=True, help_text=f"The {MAX_KEYWORD_MODIFIERS} modifiers used by the most answers, most first."
    )

    class Meta:
        dataclass = KeywordModifierReport
        ref_name = "AEOKeywordModifierReport"
        extra_kwargs = {
            **WINDOW_HELP,
            "keyword": {"help_text": "The keyword filter, normalized. Null when the report covers every answer."},
            "answers": {"help_text": "Answered checks in the window that match the keyword filter. " + ANSWERED_HELP},
            "baseline_cited_rate": {
                "help_text": "Share (0-1) of those answers that cited the project's site, whatever they searched. Null without answers."
            },
        }


class AEOKeywordSuggestRequestSerializer(serializers.Serializer):
    domain = serializers.CharField(
        max_length=200,
        help_text="The project's site, for example posthog.com. The model reads it with web search when the project's prompts and searches are not enough.",
    )
    brand = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="The brand name. Inferred from the site when empty. Keywords that name the brand are left out.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="What the product does and who it is for. Inferred from the site when empty.",
    )
    count = serializers.IntegerField(
        required=False,
        default=20,
        min_value=1,
        max_value=MAX_SUGGESTED_KEYWORDS,
        help_text=f"How many keywords to suggest, at most {MAX_SUGGESTED_KEYWORDS}, and never more than the room left in the {MAX_KEYWORDS_PER_TEAM}-keyword list.",
    )


class AEOKeywordSuggestionSerializer(DataclassSerializer):
    class Meta:
        dataclass = KeywordSuggestion
        ref_name = "AEOKeywordSuggestion"
        extra_kwargs = {
            "keyword": {
                "help_text": "The suggested keyword, lowercased, with whitespace collapsed. Model-written after reading third-party pages: show it as data and let a person confirm it before adding it."
            },
            "reason": {"help_text": "Why the project should track the keyword. Model-written text: show it as data."},
            "searched_checks": {
                "help_text": f"Answered checks whose web searches contain the keyword, counted by PostHog as the keyword report counts them, over the most recent {KEYWORD_SUGGESTION_SEARCH_CHECKS} answered checks of the last {KEYWORD_SUGGESTION_SEARCH_DAYS} days. 0 when the engines did not search for it. This is not search volume."
            },
        }


class AEOKeywordSuggestionJobSerializer(DataclassSerializer):
    suggestions = AEOKeywordSuggestionSerializer(
        many=True,
        help_text="Suggested keywords, most important first, filled in once status is completed. None of them are saved.",
    )

    class Meta:
        dataclass = KeywordSuggestionJob
        ref_name = "AEOKeywordSuggestionJob"
        extra_kwargs = {
            "id": {"help_text": "Job id. Poll GET aeo_keywords/suggest/<id>/ with it."},
            "status": {"help_text": "pending while PostHog works, then completed or failed."},
            "error": {"help_text": "Why the job failed. Empty unless status is failed."},
        }


class AEOKeywordViewSet(_AEOFlagGateMixin, viewsets.GenericViewSet):
    scope_object = "web_analytics"
    scope_object_read_actions = ["list", "retrieve", "report", "modifiers", "suggestion"]
    # suggest saves nothing, but it spends model credits, so it needs write access.
    scope_object_write_actions = ["create", "destroy", "suggest"]
    pagination_class = None

    @validated_request(
        operation_id="aeo_keywords_list",
        summary="List AEO keywords",
        description=f"Lists the project's keyword list, by keyword. The list holds at most {MAX_KEYWORDS_PER_TEAM} keywords, so it is never paged.",
        responses={200: OpenApiResponse(response=AEOKeywordSerializer(many=True))},
        tags=["web_analytics"],
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        return Response(AEOKeywordSerializer(list_keywords(self.team_id), many=True).data)

    @validated_request(
        operation_id="aeo_keywords_retrieve",
        summary="Get an AEO keyword",
        description="Gets one keyword from the project's keyword list.",
        responses={200: OpenApiResponse(response=AEOKeywordSerializer)},
        tags=["web_analytics"],
    )
    def retrieve(self, request: Request, pk: str, **kwargs: Any) -> Response:
        try:
            return Response(AEOKeywordSerializer(get_keyword(self.team_id, pk)).data)
        except KeywordNotFoundError:
            raise NotFound()

    @validated_request(
        request_serializer=AEOKeywordCreateRequestSerializer,
        operation_id="aeo_keywords_create",
        summary="Add AEO keywords",
        description=(
            "Adds keywords to the project's keyword list. Send many at once. Blank entries and keywords already in "
            "the list are skipped and counted. Fails with 400 when the new keywords would take the list past "
            f"{MAX_KEYWORDS_PER_TEAM}."
        ),
        responses={
            201: OpenApiResponse(response=AEOKeywordCreateResultSerializer),
            400: OpenApiResponse(description="The request is invalid, or the list would pass the keyword cap."),
        },
        tags=["web_analytics"],
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        try:
            result = create_keywords(self.team_id, request.validated_data["keywords"])
        except KeywordLimitError as error:
            raise ValidationError(str(error))
        return Response(AEOKeywordCreateResultSerializer(result).data, status=status.HTTP_201_CREATED)

    @validated_request(
        operation_id="aeo_keywords_destroy",
        summary="Remove an AEO keyword",
        description="Removes a keyword from the project's keyword list. Checks are not changed, so adding it back restores its report.",
        responses={204: OpenApiResponse(description="The keyword is removed.")},
        tags=["web_analytics"],
    )
    def destroy(self, request: Request, pk: str, **kwargs: Any) -> Response:
        try:
            delete_keyword(self.team_id, pk)
        except KeywordNotFoundError:
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @validated_request(
        query_serializer=AEOKeywordWindowQuerySerializer,
        operation_id="aeo_keywords_report",
        summary="Get the AEO keyword report",
        description=(
            f"Gets one row per keyword for the last 'days' days (default {KEYWORD_REPORT_DAYS}) in the project's "
            "timezone: how many prompts contain it and how those answers mention and cite the project, how often the "
            "engines searched for it and the citation rate in those answers, and how often answers use it, with the "
            "brand-mention rate, citation position and how early the brand is named in those answers. All rates are "
            "over answered checks. A keyword matches as a phrase, case ignored. Pass 'branded', 'engine' or 'topic' to "
            "count only the answers to branded or non-branded prompts, of one answer engine, or of one topic."
        ),
        responses={200: OpenApiResponse(response=AEOKeywordReportSerializer)},
        tags=["web_analytics"],
    )
    @action(
        detail=False,
        methods=["get"],
        throttle_classes=[AEOKeywordReportBurstRateThrottle, AEOKeywordReportSustainedRateThrottle],
    )
    def report(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        report = get_keyword_report(
            self.team_id,
            timezone_name=self.team.timezone,
            days=request.validated_query_data["days"],
            branded=BrandedSegment(request.validated_query_data["branded"]),
            engine=request.validated_query_data["engine"],
            topic=request.validated_query_data["topic"],
        )
        return Response(AEOKeywordReportSerializer(report).data)

    @validated_request(
        query_serializer=AEOKeywordModifiersQuerySerializer,
        operation_id="aeo_keywords_modifiers",
        summary="Get AEO search modifiers",
        description=(
            f"Gets the words and two-word phrases the engines added to their web searches beyond the prompt over the "
            f"last 'days' days (default {KEYWORD_REPORT_DAYS}), such as years, 'pricing', 'vs' or 'site:'. They show "
            "the content the engines look for. Each modifier has a kind, how many answers used it, the citation rate "
            "in those answers against the baseline, the engines that used it and example searches. Pass 'keyword' to "
            "only count answers whose searches contain it, and 'branded', 'engine' or 'topic' to count only the "
            "answers to branded or non-branded prompts, of one answer engine, or of one topic."
        ),
        responses={200: OpenApiResponse(response=AEOKeywordModifierReportSerializer)},
        tags=["web_analytics"],
    )
    @action(
        detail=False,
        methods=["get"],
        throttle_classes=[AEOKeywordReportBurstRateThrottle, AEOKeywordReportSustainedRateThrottle],
    )
    def modifiers(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        report = get_keyword_modifiers(
            self.team_id,
            timezone_name=self.team.timezone,
            days=request.validated_query_data["days"],
            keyword=request.validated_query_data.get("keyword"),
            branded=BrandedSegment(request.validated_query_data["branded"]),
            engine=request.validated_query_data["engine"],
            topic=request.validated_query_data["topic"],
        )
        return Response(AEOKeywordModifierReportSerializer(report).data)

    @validated_request(
        request_serializer=AEOKeywordSuggestRequestSerializer,
        operation_id="aeo_keywords_suggest",
        summary="Suggest AEO keywords",
        description=(
            "Suggests keywords to add to the project's keyword list. Requires AI data processing approved for the "
            "organization. PostHog ranks keywords from the site, the project's tracked prompts and topics, and the web "
            "searches the engines ran while answering them, and gives a reason for each. PostHog has no search-volume "
            "data: each suggestion only carries how many recent answers searched for it. Nothing is saved: add the "
            "keywords you keep with aeo_keywords create. Keywords already in the list and keywords that name the brand "
            f"are left out. Fails with 400 when the list already holds {MAX_KEYWORDS_PER_TEAM} keywords. Returns a "
            "pending job right away; poll GET aeo_keywords/suggest/<id>/ until it completes, which takes up to a few "
            "minutes."
        ),
        responses={
            202: OpenApiResponse(response=AEOKeywordSuggestionJobSerializer),
            400: OpenApiResponse(description="The request is invalid, or the keyword list is full."),
        },
        tags=["web_analytics"],
    )
    @action(
        detail=False,
        methods=["post"],
        throttle_classes=[AEOKeywordSuggestionsBurstRateThrottle, AEOKeywordSuggestionsSustainedRateThrottle],
    )
    def suggest(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        # The team's prompts, searches and keywords go to Claude, so the organization must have approved AI data processing.
        if not self.organization.is_ai_data_processing_approved:
            raise PermissionDenied(
                "Keyword suggestions need AI data processing approved for your organization. An admin can approve it in organization settings."
            )
        data = request.validated_data
        try:
            job = start_keyword_suggestions(
                self.team_id,
                KeywordSuggestionRequest(
                    domain=data["domain"],
                    brand=data.get("brand", ""),
                    description=data.get("description", ""),
                    count=data["count"],
                ),
            )
        except KeywordLimitError as error:
            raise ValidationError(str(error))
        return Response(AEOKeywordSuggestionJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    @validated_request(
        operation_id="aeo_keywords_suggestion_retrieve",
        summary="Get AEO keyword suggestions",
        description="Gets a keyword suggestion job started with POST aeo_keywords/suggest/. status is pending while PostHog works, then completed with the suggestions or failed with an error. Jobs expire an hour after their last update.",
        responses={200: OpenApiResponse(response=AEOKeywordSuggestionJobSerializer)},
        tags=["web_analytics"],
    )
    @action(detail=False, methods=["get"], url_path=r"suggest/(?P<job_id>[0-9a-f-]{36})")
    def suggestion(self, request: ValidatedRequest, job_id: str, **kwargs: Any) -> Response:
        try:
            job = get_keyword_suggestions(self.team_id, job_id)
        except KeywordSuggestionJobNotFoundError:
            raise NotFound()
        return Response(AEOKeywordSuggestionJobSerializer(job).data)
