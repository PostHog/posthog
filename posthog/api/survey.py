from contextlib import contextmanager

from django.db.models import Min
from django.http import JsonResponse
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_token
from posthog.client import sync_execute
from posthog.exceptions import generate_exception_response
from posthog.models.feedback.survey import Survey
from rest_framework.response import Response
from rest_framework.decorators import action
from posthog.api.feature_flag import (
    BEHAVIOURAL_COHORT_FOUND_ERROR_CODE,
    FeatureFlagSerializer,
    MinimalFeatureFlagSerializer,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework import serializers, viewsets, request
from rest_framework.request import Request
from rest_framework import status

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.team.team import Team
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from nanoid import generate

from typing import Any

from posthog.utils_cors import cors_response

import nh3

from urllib.parse import urlparse

SURVEY_TARGETING_FLAG_PREFIX = "survey-targeting-"
ALLOWED_LINK_URL_SCHEMES = ["https", "mailto"]


class SurveySerializer(serializers.ModelSerializer):
    linked_flag_id = serializers.IntegerField(required=False, allow_null=True, source="linked_flag.id")
    linked_flag = MinimalFeatureFlagSerializer(read_only=True)
    targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    internal_targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Survey
        fields = [
            "id",
            "name",
            "description",
            "type",
            "linked_flag",
            "linked_flag_id",
            "targeting_flag",
            "internal_targeting_flag",
            "questions",
            "conditions",
            "appearance",
            "created_at",
            "created_by",
            "start_date",
            "end_date",
            "archived",
            "responses_limit",
            "iteration_count",
            "iteration_frequency_days",
            "iteration_start_dates",
            "current_iteration",
            "current_iteration_start_date",
        ]
        read_only_fields = ["id", "created_at", "created_by"]


class SurveySerializerCreateUpdateOnly(SurveySerializer):
    linked_flag_id = serializers.IntegerField(required=False, write_only=True, allow_null=True)
    targeting_flag_id = serializers.IntegerField(required=False, write_only=True)
    targeting_flag_filters = serializers.JSONField(required=False, write_only=True, allow_null=True)
    remove_targeting_flag = serializers.BooleanField(required=False, write_only=True, allow_null=True)

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
            "remove_targeting_flag",
            "questions",
            "conditions",
            "appearance",
            "created_at",
            "created_by",
            "start_date",
            "end_date",
            "archived",
            "responses_limit",
            "iteration_count",
            "iteration_frequency_days",
            "iteration_start_dates",
            "current_iteration",
            "current_iteration_start_date",
        ]
        read_only_fields = ["id", "linked_flag", "targeting_flag", "created_at"]

    def validate_appearance(self, value):
        if value is None:
            return value

        if not isinstance(value, dict):
            raise serializers.ValidationError("Appearance must be an object")

        thank_you_message = value.get("thankYouMessageHeader")
        if thank_you_message and nh3.is_html(thank_you_message):
            value["thankYouMessageHeader"] = nh3_clean_with_allow_list(thank_you_message)

        thank_you_description = value.get("thankYouMessageDescription")
        if thank_you_description and nh3.is_html(thank_you_description):
            value["thankYouMessageDescription"] = nh3_clean_with_allow_list(thank_you_description)

        return value

    def validate_questions(self, value):
        if value is None:
            return value

        if not isinstance(value, list):
            raise serializers.ValidationError("Questions must be a list of objects")

        cleaned_questions = []
        for raw_question in value:
            if not isinstance(raw_question, dict):
                raise serializers.ValidationError("Questions must be a list of objects")

            cleaned_question = {
                **raw_question,
            }
            question_text = raw_question.get("question")

            if not question_text:
                raise serializers.ValidationError("Question text is required")

            description = raw_question.get("description")
            if nh3.is_html(question_text):
                cleaned_question["question"] = nh3_clean_with_allow_list(question_text)
            if description and nh3.is_html(description):
                cleaned_question["description"] = nh3_clean_with_allow_list(description)

            choices = raw_question.get("choices")
            if choices and not isinstance(choices, list):
                raise serializers.ValidationError("Question choices must be a list of strings")

            link = raw_question.get("link")
            if link:
                parsed_url = urlparse(link)
                if parsed_url.scheme not in ALLOWED_LINK_URL_SCHEMES or parsed_url.netloc == "":
                    raise serializers.ValidationError(
                        f"Link must be a URL to resource with one of these schemes [{', '.join(ALLOWED_LINK_URL_SCHEMES)}]"
                    )

            cleaned_questions.append(cleaned_question)

        return cleaned_questions

    def validate(self, data):
        linked_flag_id = data.get("linked_flag_id")
        if linked_flag_id:
            try:
                FeatureFlag.objects.get(pk=linked_flag_id)
            except FeatureFlag.DoesNotExist:
                raise serializers.ValidationError("Feature Flag with this ID does not exist")

        if (
            self.context["request"].method == "POST"
            and Survey.objects.filter(name=data.get("name"), team_id=self.context["team_id"]).exists()
        ):
            raise serializers.ValidationError("There is already a survey with this name.", code="unique")

        existing_survey: Survey | None = self.instance

        if (
            existing_survey
            and existing_survey.name != data.get("name")
            and Survey.objects.filter(name=data.get("name"), team_id=self.context["team_id"])
            .exclude(id=existing_survey.id)
            .exists()
        ):
            raise serializers.ValidationError("There is already another survey with this name.", code="unique")

        if data.get("targeting_flag_filters"):
            groups = (data.get("targeting_flag_filters") or {}).get("groups") or []
            full_rollout = any(
                group.get("rollout_percentage") in [100, None] and len(group.get("properties", [])) == 0
                for group in groups
            )

            if full_rollout:
                raise serializers.ValidationError(
                    "Invalid operation: User targeting rolls out to everyone. If you want to roll out to everyone, delete this targeting",
                    code="invalid",
                )
        return data

    def create(self, validated_data):
        if "remove_targeting_flag" in validated_data:
            validated_data.pop("remove_targeting_flag")

        validated_data["team_id"] = self.context["team_id"]
        if validated_data.get("targeting_flag_filters"):
            targeting_feature_flag = self._create_or_update_targeting_flag(
                None, validated_data["targeting_flag_filters"], validated_data["name"]
            )
            validated_data["targeting_flag_id"] = targeting_feature_flag.id
            validated_data.pop("targeting_flag_filters")

        if "targeting_flag_filters" in validated_data:
            validated_data.pop("targeting_flag_filters")

        validated_data["created_by"] = self.context["request"].user
        instance = super().create(validated_data)
        self._add_user_survey_interacted_filters(instance)

        return instance

    def update(self, instance: Survey, validated_data):
        if validated_data.get("remove_targeting_flag"):
            if instance.targeting_flag:
                instance.targeting_flag.delete()
                validated_data["targeting_flag_id"] = None
            validated_data.pop("remove_targeting_flag")

            # make sure instance.targeting_flag is gone
            instance.refresh_from_db()

        # if the target flag filters come back with data, update the targeting feature flag if there is one, otherwise create a new one
        if validated_data.get("targeting_flag_filters"):
            new_filters = validated_data["targeting_flag_filters"]
            if instance.targeting_flag:
                existing_targeting_flag = instance.targeting_flag
                serialized_data_filters = {
                    **existing_targeting_flag.filters,
                    **new_filters,
                }
                self._create_or_update_targeting_flag(instance.targeting_flag, serialized_data_filters)
            else:
                new_flag = self._create_or_update_targeting_flag(
                    None, new_filters, instance.name, bool(instance.start_date)
                )
                validated_data["targeting_flag_id"] = new_flag.id
            validated_data.pop("targeting_flag_filters")

        end_date = validated_data.get("end_date")
        if instance.targeting_flag:
            # turn off feature flag if survey is completed
            if end_date is None:
                instance.targeting_flag.active = True
            else:
                instance.targeting_flag.active = False
            instance.targeting_flag.save()

        if instance.current_iteration is not None and instance.current_iteration > validated_data.get(
            "iteration_count"
        ):
            raise serializers.ValidationError(
                f"Cannot change survey recurrence to {validated_data.get('iteration_count')}, should be at least {instance.current_iteration}"
            )

        instance.iteration_count = validated_data.get("iteration_count")
        instance.iteration_frequency_days = validated_data.get("iteration_frequency_days")

        instance = super().update(instance, validated_data)
        # if "iteration_count" in validated_data and "iteration_frequency_days" in validated_data:
        #     iteration_count = validated_data.get("iteration_count")
        #
        #     if instance.current_iteration is not None and instance.current_iteration > iteration_count:
        #         raise serializers.ValidationError(
        #             f"Cannot change survey recurrence to {iteration_count}, should be at least {instance.current_iteration}"
        #         )
        #
        #     instance.update_survey_iteration_count(iteration_count, validated_data.get("iteration_frequency_days"))
        # else:
        #     instance.iteration_start_dates = []
        #     instance.current_iteration = None
        #     instance.current_iteration_start_date = None
        #     instance.save()

        self._add_user_survey_interacted_filters(instance, end_date)
        return instance

    def _add_user_survey_interacted_filters(self, instance: Survey, end_date=None):
        user_submitted_dismissed_filter = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": [
                        {
                            "key": f"$survey_dismissed/{instance.id}",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                            "type": "person",
                        },
                        {
                            "key": f"$survey_responded/{instance.id}",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                            "type": "person",
                        },
                    ],
                }
            ]
        }

        if instance.internal_targeting_flag:
            existing_targeting_flag = instance.internal_targeting_flag
            serialized_data_filters = {**user_submitted_dismissed_filter, **existing_targeting_flag.filters}

            internal_targeting_flag = self._create_or_update_targeting_flag(
                instance.internal_targeting_flag, serialized_data_filters, flag_name_suffix="-custom"
            )

            internal_targeting_flag.active = bool(instance.start_date) and not end_date
            internal_targeting_flag.save()

            instance.internal_targeting_flag_id = internal_targeting_flag.id

            instance.save()
        else:
            new_flag = self._create_or_update_targeting_flag(
                None,
                user_submitted_dismissed_filter,
                instance.name,
                bool(instance.start_date) and not end_date,
                flag_name_suffix="-custom",
            )
            instance.internal_targeting_flag_id = new_flag.id
            instance.save()

    def _create_or_update_targeting_flag(
        self, existing_flag=None, filters=None, name=None, active=False, flag_name_suffix=None
    ):
        with create_flag_with_survey_errors():
            if existing_flag:
                existing_flag_serializer = FeatureFlagSerializer(
                    existing_flag,
                    data={"filters": filters},
                    partial=True,
                    context=self.context,
                )
                existing_flag_serializer.is_valid(raise_exception=True)
                return existing_flag_serializer.save()
            elif name and filters:
                random_id = generate("1234567890abcdef", 10)
                feature_flag_key = slugify(f"{SURVEY_TARGETING_FLAG_PREFIX}{random_id}{flag_name_suffix or ''}")
                feature_flag_serializer = FeatureFlagSerializer(
                    data={
                        "key": feature_flag_key,
                        "name": f"Targeting flag for survey {name}",
                        "filters": filters,
                        "active": active,
                    },
                    context=self.context,
                )

                feature_flag_serializer.is_valid(raise_exception=True)
                return feature_flag_serializer.save()
            else:
                raise serializers.ValidationError("Targeting flag for survey failed, invalid parameters.")


class SurveyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "survey"
    queryset = Survey.objects.select_related("linked_flag", "targeting_flag", "internal_targeting_flag").all()

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.request.method == "POST" or self.request.method == "PATCH":
            return SurveySerializerCreateUpdateOnly
        else:
            return SurveySerializer

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        related_targeting_flag = instance.targeting_flag
        if related_targeting_flag:
            related_targeting_flag.delete()

        related_internal_targeting_flag = instance.internal_targeting_flag
        if related_internal_targeting_flag:
            related_internal_targeting_flag.delete()

        return super().destroy(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def responses_count(self, request: request.Request, **kwargs):
        earliest_survey_creation_date = Survey.objects.filter(team_id=self.team_id).aggregate(Min("created_at"))[
            "created_at__min"
        ]
        data = sync_execute(
            f"""
            SELECT JSONExtractString(properties, '$survey_id') as survey_id, count()
            FROM events
            WHERE event = 'survey sent' AND team_id = %(team_id)s AND timestamp >= %(timestamp)s
            GROUP BY survey_id
        """,
            {"team_id": self.team_id, "timestamp": earliest_survey_creation_date},
        )

        counts = {}
        for survey_id, count in data:
            counts[survey_id] = count

        return Response(counts)


class SurveyAPISerializer(serializers.ModelSerializer):
    """
    Serializer for the exposed /api/surveys endpoint, to be used in posthog-js and for headless APIs.
    """

    linked_flag_key = serializers.CharField(source="linked_flag.key", read_only=True)
    targeting_flag_key = serializers.CharField(source="targeting_flag.key", read_only=True)
    internal_targeting_flag_key = serializers.CharField(source="internal_targeting_flag.key", read_only=True)

    class Meta:
        model = Survey
        fields = [
            "id",
            "name",
            "description",
            "type",
            "linked_flag_key",
            "targeting_flag_key",
            "internal_targeting_flag_key",
            "questions",
            "conditions",
            "appearance",
            "start_date",
            "end_date",
            "current_iteration",
        ]
        read_only_fields = fields


@csrf_exempt
def surveys(request: Request):
    token = get_token(None, request)

    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "surveys",
                "API key not provided. You can find your project API key in your PostHog project settings.",
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
                "surveys",
                "Project API key invalid. You can find your project API key in your PostHog project settings.",
                type="authentication_error",
                code="invalid_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    surveys = SurveyAPISerializer(
        Survey.objects.filter(team_id=team.id)
        .exclude(archived=True)
        .select_related("linked_flag", "targeting_flag", "internal_targeting_flag"),
        many=True,
    ).data

    return cors_response(request, JsonResponse({"surveys": surveys}))


@contextmanager
def create_flag_with_survey_errors():
    # context manager to raise error with a different message when flag creation fails
    try:
        yield
    except serializers.ValidationError as e:
        # get the full details of the error to figure out if it's a behavioural cohort error
        error_details = e.get_full_details()
        matching_errors = [
            detail
            for detail in error_details.get("filters", [{}])
            if detail.get("code") == BEHAVIOURAL_COHORT_FOUND_ERROR_CODE
        ]
        if matching_errors:
            original_detail = matching_errors[0].get("message")
            raise serializers.ValidationError(
                detail=original_detail.replace("feature flags", "surveys"),
                code=BEHAVIOURAL_COHORT_FOUND_ERROR_CODE,
            )
        raise e


def nh3_clean_with_allow_list(to_clean: str):
    return nh3.clean(
        to_clean,
        link_rel="noopener",
        tags={
            "a",
            "abbr",
            "acronym",
            "area",
            "article",
            "aside",
            "b",
            "bdi",
            "bdo",
            "blockquote",
            "br",
            "caption",
            "center",
            "cite",
            "code",
            "col",
            "colgroup",
            "data",
            "dd",
            "del",
            "details",
            "dfn",
            "div",
            "dl",
            "dt",
            "em",
            "figcaption",
            "figure",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "hgroup",
            "hr",
            "i",
            "img",
            "ins",
            "kbd",
            "li",
            "map",
            "mark",
            "nav",
            "ol",
            "p",
            "pre",
            "q",
            "rp",
            "rt",
            "rtc",
            "ruby",
            "s",
            "samp",
            "small",
            "span",
            "strike",
            "strong",
            "sub",
            "summary",
            "sup",
            "table",
            "tbody",
            "td",
            "th",
            "thead",
            "time",
            "tr",
            "tt",
            "u",
            "ul",
            "var",
            "wbr",
        },
        attributes={
            "*": {"style", "lang", "title", "width", "height"},
            # below are mostly defaults to ammonia, but we need to add them explicitly
            # because this python binding doesn't allow additive allowing
            "a": {"href", "hreflang", "target"},
            "bdo": {"dir"},
            "blockquote": {"cite"},
            "col": {"align", "char", "charoff", "span"},
            "colgroup": {"align", "char", "charoff", "span"},
            "del": {"cite", "datetime"},
            "hr": {"align", "size", "width"},
            "img": {"align", "alt", "height", "src", "width"},
            "ins": {"cite", "datetime"},
            "ol": {"start", "type"},
            "q": {"cite"},
            "table": {
                "align",
                "bgcolor",
                "border",
                "cellpadding",
                "cellspacing",
                "frame",
                "rules",
                "summary",
                "width",
            },
            "tbody": {"align", "char", "charoff", "valign"},
            "td": {
                "abbr",
                "align",
                "axis",
                "bgcolor",
                "char",
                "charoff",
                "colspan",
                "headers",
                "height",
                "nowrap",
                "rowspan",
                "scope",
                "valign",
                "width",
            },
            "tfoot": {"align", "char", "charoff", "valign"},
            "th": {
                "abbr",
                "align",
                "axis",
                "bgcolor",
                "char",
                "charoff",
                "colspan",
                "headers",
                "height",
                "nowrap",
                "rowspan",
                "scope",
                "valign",
                "width",
            },
            "thead": {"align", "char", "charoff", "valign"},
            "tr": {"align", "bgcolor", "char", "charoff", "valign"},
        },
    )
