import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict, cast
from urllib.parse import urlparse
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Min
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

import nh3
import structlog
import posthoganalytics
from axes.decorators import axes_dispatch
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from nanoid import generate
from posthoganalytics import capture_exception
from prometheus_client import Counter
from rest_framework import exceptions, filters, request, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.action import ActionSerializer, ActionStepJSONSerializer
from posthog.api.feature_flag import (
    BEHAVIOURAL_COHORT_FOUND_ERROR_CODE,
    FeatureFlagSerializer,
    MinimalFeatureFlagSerializer,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action, get_token
from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.constants import SURVEY_TARGETING_FLAG_PREFIX, AvailableFeature
from posthog.event_usage import report_user_action
from posthog.exceptions import generate_exception_response
from posthog.models import Action
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.feature_flag import FeatureFlag
from posthog.models.surveys.survey import MAX_ITERATION_COUNT, Survey, ensure_question_ids, surveys_hypercache
from posthog.models.surveys.survey_response_archive import SurveyResponseArchive
from posthog.models.surveys.util import (
    SurveyEventName,
    SurveyEventProperties,
    get_archived_response_uuids,
    get_unique_survey_event_uuids_sql_subquery,
)
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDT
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.utils_cors import cors_response

from products.surveys.backend.summarization import fetch_responses, format_as_markdown, summarize_responses

from ee.surveys.summaries.headline_summary import generate_survey_headline

# Constants for better maintainability
logger = structlog.get_logger(__name__)
CACHE_TIMEOUT_SECONDS = 300

ALLOWED_LINK_URL_SCHEMES = ["https", "mailto"]
EMAIL_REGEX = r"^mailto:[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
FIELDS_NOT_APPLICABLE_TO_EXTERNAL_SURVEYS = [
    "linked_flag_id",
    "targeting_flag_filters",
]

# Does not include actions or events, as those are objects and thus are evaluated differently
CONDITION_FIELDS_NOT_APPLICABLE_TO_EXTERNAL_SURVEYS = [
    "url",
    "urlMatchType",
    "selector",
    "seenSurveyWaitPeriodInDays",
    "linkedFlagVariant",
    "deviceTypes",
    "deviceTypesMatchType",
]


if "replica" in settings.DATABASES:
    READ_DB_FOR_SURVEYS = "replica"
else:
    READ_DB_FOR_SURVEYS = "default"


COUNTER_SURVEYS_API_USE_REMOTE_CONFIG = Counter(
    "posthog_surveys_api_use_remote_config",
    "Number of times the surveys API has been used with remote config",
    labelnames=["result"],
)

COUNTER_SURVEYS_API_REMOTE_CONFIG_COMPARISON = Counter(
    "posthog_surveys_api_remote_config_comparison",
    "Comparison of surveys response equality",
    labelnames=["result"],
)


class EventStats(TypedDict):
    total_count: int
    total_count_only_seen: int
    unique_persons: int
    unique_persons_only_seen: int  # unique_persons - dismissed - sent
    first_seen: str | None
    last_seen: str | None


class SurveyRates(TypedDict):
    response_rate: float
    dismissal_rate: float
    unique_users_response_rate: float
    unique_users_dismissal_rate: float


# Ideally we'd use SurveyEventName here, but enum values are not valid as keys in TypedDicts
SurveyStats = TypedDict(
    "SurveyStats",
    {
        "survey shown": EventStats,
        "survey dismissed": EventStats,
        "survey sent": EventStats,
    },
)


def get_survey_conditions_with_actions(
    survey: "Survey", action_serializer_class: type[serializers.Serializer] | None = None
) -> dict | None:
    if action_serializer_class is None:
        action_serializer_class = ActionSerializer
    conditions = survey.conditions
    actions = survey.actions.all()
    if len(actions) > 0:
        if conditions is None:
            conditions = {}
        else:
            conditions = dict(conditions)
        conditions["actions"] = {"values": action_serializer_class(actions, many=True).data}
    return conditions


class SurveySerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    linked_flag_id = serializers.IntegerField(required=False, allow_null=True, source="linked_flag.id")
    linked_flag = MinimalFeatureFlagSerializer(read_only=True)
    linked_insight_id = serializers.IntegerField(required=False, allow_null=True, source="linked_insight.id")
    targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    internal_targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    conditions = serializers.SerializerMethodField(method_name="get_conditions", read_only=True)
    feature_flag_keys = serializers.SerializerMethodField()
    # NB this is enforced in the UI too
    iteration_count = serializers.IntegerField(
        required=False, allow_null=True, max_value=MAX_ITERATION_COUNT, min_value=0
    )
    schedule = serializers.CharField(required=False, allow_null=True)
    enable_partial_responses = serializers.BooleanField(required=False, allow_null=True)

    def get_feature_flag_keys(self, survey: Survey) -> list:
        return [
            {"key": "linked_flag_key", "value": survey.linked_flag.key if survey.linked_flag else None},
            {"key": "targeting_flag_key", "value": survey.targeting_flag.key if survey.targeting_flag else None},
            {
                "key": "internal_targeting_flag_key",
                "value": survey.internal_targeting_flag.key if survey.internal_targeting_flag else None,
            },
            {
                "key": "internal_response_sampling_flag_key",
                "value": survey.internal_response_sampling_flag.key if survey.internal_response_sampling_flag else None,
            },
        ]

    class Meta:
        model = Survey
        fields = [
            "id",
            "name",
            "description",
            "type",
            "schedule",
            "linked_flag",
            "linked_flag_id",
            "linked_insight_id",
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
            "feature_flag_keys",
            "iteration_count",
            "iteration_frequency_days",
            "iteration_start_dates",
            "current_iteration",
            "current_iteration_start_date",
            "response_sampling_start_date",
            "response_sampling_interval_type",
            "response_sampling_interval",
            "response_sampling_limit",
            "response_sampling_daily_limits",
            "enable_partial_responses",
            "user_access_level",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def get_conditions(self, survey: Survey):
        return get_survey_conditions_with_actions(survey)


class SurveySerializerCreateUpdateOnly(serializers.ModelSerializer):
    linked_flag = MinimalFeatureFlagSerializer(read_only=True)
    linked_flag_id = serializers.IntegerField(required=False, write_only=True, allow_null=True)
    linked_insight_id = serializers.IntegerField(required=False, write_only=True, allow_null=True)
    targeting_flag_id = serializers.IntegerField(required=False, write_only=True)
    targeting_flag_filters = serializers.JSONField(required=False, write_only=True, allow_null=True)
    remove_targeting_flag = serializers.BooleanField(required=False, write_only=True, allow_null=True)
    targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    internal_targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    # NB this is enforced in the UI too
    iteration_count = serializers.IntegerField(
        required=False, allow_null=True, max_value=MAX_ITERATION_COUNT, min_value=0
    )
    schedule = serializers.CharField(required=False, allow_null=True)
    enable_partial_responses = serializers.BooleanField(required=False, allow_null=True)
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Survey
        fields = [
            "id",
            "name",
            "description",
            "type",
            "schedule",
            "linked_flag",
            "linked_flag_id",
            "linked_insight_id",
            "targeting_flag_id",
            "targeting_flag",
            "internal_targeting_flag",
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
            "response_sampling_start_date",
            "response_sampling_interval_type",
            "response_sampling_interval",
            "response_sampling_limit",
            "response_sampling_daily_limits",
            "enable_partial_responses",
            "_create_in_folder",
        ]
        read_only_fields = ["id", "linked_flag", "targeting_flag", "created_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["conditions"] = get_survey_conditions_with_actions(instance)
        return data

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

        thank_you_description_content_type = value.get("thankYouMessageDescriptionContentType")
        if thank_you_description_content_type and thank_you_description_content_type not in ["text", "html"]:
            raise serializers.ValidationError("thankYouMessageDescriptionContentType must be one of ['text', 'html']")

        survey_popup_delay_seconds = value.get("surveyPopupDelaySeconds")
        if survey_popup_delay_seconds and survey_popup_delay_seconds < 0:
            raise serializers.ValidationError("Survey popup delay seconds must be a positive integer")

        survey_white_label = value.get("whiteLabel")
        if survey_white_label is not None and not isinstance(survey_white_label, bool):
            raise serializers.ValidationError("whiteLabel must be a boolean")

        # Check if the organization has the white labelling feature available
        use_survey_white_labelling = self.context["request"].user.organization.is_feature_available(
            AvailableFeature.WHITE_LABELLING
        )

        if survey_white_label and not use_survey_white_labelling:
            raise serializers.ValidationError("You need to upgrade to PostHog Enterprise to use white labelling")

        return value

    def validate_conditions(self, value):
        if value is None:
            return value

        if not isinstance(value, dict):
            raise serializers.ValidationError("Conditions must be an object")

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

            description_content_type = raw_question.get("descriptionContentType")
            if description_content_type and description_content_type not in ["text", "html"]:
                raise serializers.ValidationError("Question descriptionContentType must be one of ['text', 'html']")

            choices = raw_question.get("choices")
            if choices:
                if not isinstance(choices, list):
                    raise serializers.ValidationError("Question choices must be a list of strings")
                if any(not choice.strip() for choice in choices):
                    raise serializers.ValidationError("Question choices cannot be empty")

            link = raw_question.get("link")
            if link:
                parsed_url = urlparse(link)

                # Check for unsupported schemes
                if parsed_url.scheme not in ALLOWED_LINK_URL_SCHEMES:
                    raise serializers.ValidationError(
                        f"Link must be a URL with one of these schemes: [{', '.join(ALLOWED_LINK_URL_SCHEMES)}]"
                    )

                # Separate validation for `mailto:` links
                if parsed_url.scheme == "mailto":
                    if not re.match(EMAIL_REGEX, link):
                        raise serializers.ValidationError(
                            "Invalid mailto link. Please enter a valid mailto link (e.g., mailto:example@domain.com)."
                        )
                # HTTPS validation
                elif parsed_url.scheme == "https":
                    if not parsed_url.netloc:
                        raise serializers.ValidationError("Invalid HTTPS URL. Please enter a valid HTTPS link.")

            cleaned_questions.append(cleaned_question)

        return cleaned_questions

    def validate_schedule(self, value):
        if value is not None and value not in ["once", "recurring", "always"]:
            raise serializers.ValidationError("Schedule must be one of: once, recurring, always")
        return value

    def validate(self, data):
        linked_flag_id = data.get("linked_flag_id")
        linked_flag = None
        if linked_flag_id:
            try:
                linked_flag = FeatureFlag.objects.get(pk=linked_flag_id, team_id=self.context["team_id"])
            except FeatureFlag.DoesNotExist:
                raise serializers.ValidationError("Feature Flag with this ID does not exist")

        # Validate linkedFlagVariant if provided
        conditions = data.get("conditions") or {}
        linked_flag_variant = conditions.get("linkedFlagVariant")
        if linked_flag_variant and linked_flag and linked_flag_variant != "any":
            # Get available variants from the linked feature flag
            available_variants = [variant["key"] for variant in linked_flag.variants]
            if linked_flag_variant not in available_variants:
                if available_variants:
                    raise serializers.ValidationError(
                        f"Feature flag variant '{linked_flag_variant}' does not exist. Available variants: {', '.join(available_variants)}"
                    )
                else:
                    raise serializers.ValidationError(
                        f"Feature flag variant '{linked_flag_variant}' specified but the linked feature flag has no variants"
                    )
        elif linked_flag_variant and not linked_flag_id:
            raise serializers.ValidationError("linkedFlagVariant can only be used when a linked_flag_id is specified")

        if (
            self.context["request"].method == "POST"
            and Survey.objects.filter(name=data.get("name"), team__project_id=self.context["project_id"]).exists()
        ):
            raise serializers.ValidationError("There is already a survey with this name.", code="unique")

        existing_survey: Survey | None = self.instance

        if (
            existing_survey
            and existing_survey.name != data.get("name")
            and Survey.objects.filter(name=data.get("name"), team__project_id=self.context["project_id"])
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

        response_sampling_start_date = data.get("response_sampling_start_date")
        if response_sampling_start_date is not None:
            today_utc = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            if response_sampling_start_date < today_utc:
                raise serializers.ValidationError(
                    {
                        "response_sampling_start_date": f"Response sampling start date must be today or a future date in UTC. Got {response_sampling_start_date} when current time is {today_utc}"
                    }
                )

        response_sampling_interval = data.get("response_sampling_interval")
        if response_sampling_interval is not None and response_sampling_interval <= 0:
            raise serializers.ValidationError(
                {"response_sampling_interval": "Response sampling interval must be greater than 0."}
            )

        response_sampling_limit = data.get("response_sampling_limit", 0)
        if (
            response_sampling_limit is not None
            and response_sampling_limit > 0
            and response_sampling_interval > 0
            and response_sampling_start_date is None
        ):
            raise serializers.ValidationError(
                {
                    "response_sampling_start_date": "Response sampling start date should be set if response_sampling_start_date is not zero."
                }
            )

        # Validate that question shuffling and branching are not used together
        # Check both incoming data and existing survey data (existing_survey is None for POST)
        appearance = data.get("appearance")
        questions = data.get("questions")

        effective_appearance = {}
        if existing_survey and existing_survey.appearance:
            effective_appearance = dict(existing_survey.appearance)
        if appearance is not None:
            effective_appearance.update(appearance)

        effective_questions = (
            questions if questions is not None else (existing_survey.questions if existing_survey else [])
        )

        shuffle_questions = effective_appearance.get("shuffleQuestions", False)

        if shuffle_questions and effective_questions:
            has_branching = any(question.get("branching") is not None for question in effective_questions)

            if has_branching:
                raise serializers.ValidationError(
                    "Question shuffling and question branching cannot be used together. "
                    "Please disable one of these features."
                )

        # Validate external survey constraints
        if data.get("type") == Survey.SurveyType.EXTERNAL_SURVEY:
            errors = {}

            # Check prohibited fields
            for field in FIELDS_NOT_APPLICABLE_TO_EXTERNAL_SURVEYS:
                if data.get(field) is not None:
                    errors[field] = f"{field} is not allowed for external surveys"

            # Check prohibited condition fields
            if data.get("conditions"):
                condition_errors = []
                conditions = data["conditions"]

                # Check individual condition fields
                for field in CONDITION_FIELDS_NOT_APPLICABLE_TO_EXTERNAL_SURVEYS:
                    if field in conditions and conditions[field] is not None:
                        condition_errors.append(field)

                # Check actions/events if they have values
                for field in ["actions", "events"]:
                    if field in conditions and isinstance(conditions[field], dict):
                        values = conditions[field].get("values", [])
                        if values:
                            condition_errors.append(field)

                if condition_errors:
                    errors["conditions"] = (
                        f"The following condition fields are not allowed for external surveys: {', '.join(condition_errors)}"
                    )

            # Check prohibited appearance fields
            if "appearance" in data and data["appearance"] and "surveyPopupDelaySeconds" in data["appearance"]:
                if data["appearance"]["surveyPopupDelaySeconds"] is not None:
                    errors["appearance"] = "surveyPopupDelaySeconds is not allowed for external surveys"

            if errors:
                raise serializers.ValidationError(errors)

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
        self._associate_actions(instance, validated_data.get("conditions"))
        self._add_internal_response_sampling_filters(instance)

        team = Team.objects.get(id=self.context["team_id"])
        log_activity(
            organization_id=team.organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            item_id=instance.id,
            scope="Survey",
            activity="created",
            detail=Detail(name=instance.name),
        )

        return instance

    def update(self, instance: Survey, validated_data):
        before_update = Survey.objects.get(pk=instance.pk)
        user = self.context["request"].user
        changes = []

        if validated_data.get("remove_targeting_flag"):
            if instance.targeting_flag:
                # Manually delete the flag and log the change
                # The `changes_between` method won't catch this because the flag (and underlying ForeignKey relationship)
                # will have been deleted by the time the `changes_between` method is called, so we need to log the change manually
                changes.append(
                    Change(type="Survey", field="targeting_flag", action="deleted", before=instance.targeting_flag)
                )
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
                existing_targeting_flag_filters = existing_targeting_flag.filters
                serialized_data_filters = {
                    **existing_targeting_flag_filters,
                    **new_filters,
                }
                # Log the existing filter change
                # The `changes_between` method won't catch this because the flag (and underlying ForeignKey relationship)
                # will have been deleted by the time the `changes_between` method is called, so we need to log the change manually
                changes.append(
                    Change(
                        type="Survey",
                        field="targeting_flag_filters",
                        action="changed",
                        before=existing_targeting_flag_filters,
                        after=new_filters,
                    )
                )
                self._create_or_update_targeting_flag(instance.targeting_flag, serialized_data_filters)
            else:
                new_flag = self._create_or_update_targeting_flag(
                    None, new_filters, instance.name, bool(instance.start_date)
                )
                # Log the new filter change
                # The `changes_between` method won't catch this because the flag (and underlying ForeignKey relationship)
                # will have been deleted by the time the `changes_between` method is called, so we need to log the change manually
                changes.append(
                    Change(type="Survey", field="targeting_flag_filters", action="created", after=new_filters)
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

        iteration_count = validated_data.get("iteration_count", None)
        if (
            instance.current_iteration is not None
            and iteration_count is not None
            and instance.current_iteration > iteration_count > 0
        ):
            raise serializers.ValidationError(
                f"Cannot change survey recurrence to {iteration_count}, should be at least {instance.current_iteration}"
            )

        if iteration_count is not None:
            instance.iteration_count = iteration_count
            instance.iteration_frequency_days = validated_data.get("iteration_frequency_days")

        instance = super().update(instance, validated_data)

        team = Team.objects.get(id=self.context["team_id"])
        # `changes_between` will not catch changes to the ForeignKey relationships
        # so it's useful for any changes to the Survey model itself, but not for the related models
        non_foreign_table_relation_changes = changes_between(
            "Survey",
            previous=before_update,
            current=instance,
        )
        changes.extend(non_foreign_table_relation_changes)
        log_activity(
            organization_id=team.organization_id,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            item_id=instance.id,
            scope="Survey",
            activity="updated",
            detail=Detail(changes=changes, name=instance.name),
        )

        # Report survey events based on start_date and end_date changes

        properties = {
            "name": instance.name,
            "id": instance.id,
            "survey_type": instance.type,
            "question_types": [question.get("type") for question in instance.questions] if instance.questions else [],
            "created_at": instance.created_at,
            "start_date": instance.start_date,
            "end_date": instance.end_date,
        }
        if before_update.start_date is None and instance.start_date is not None:
            report_user_action(
                user,
                "survey launched",
                properties,
                team,
            )
        elif before_update.end_date is None and instance.end_date is not None:
            report_user_action(
                user,
                "survey stopped",
                properties,
                team,
            )
        elif before_update.start_date is not None and before_update.end_date is not None and instance.end_date is None:
            report_user_action(
                user,
                "survey resumed",
                properties,
                team,
            )

        self._add_user_survey_interacted_filters(instance, end_date)
        self._associate_actions(instance, validated_data.get("conditions"))
        self._add_internal_response_sampling_filters(instance)
        return instance

    def _add_internal_response_sampling_filters(self, instance: Survey):
        if instance.response_sampling_daily_limits is None:
            return
        if instance.internal_response_sampling_flag is not None:
            return

        sampling_filters = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": [],
                }
            ]
        }

        instance.internal_response_sampling_flag = self._create_or_update_targeting_flag(
            None, sampling_filters, instance.name, bool(instance.start_date), flag_name_suffix="-sampling"
        )
        instance.save()

    def _associate_actions(self, instance: Survey, conditions):
        if conditions is None:
            instance.actions.clear()
            return

        actions = conditions.get("actions")
        if actions is None:
            instance.actions.clear()
            return

        values = actions.get("values")
        if values is None or len(values) == 0:
            instance.actions.clear()
            return

        action_ids = (value.get("id") for value in values)

        instance.actions.set(Action.objects.filter(team__project_id=self.context["project_id"], id__in=action_ids))
        instance.save()

    def _add_user_survey_interacted_filters(self, instance: Survey, end_date=None):
        survey_key = f"{instance.id}"
        if instance.iteration_count is not None and instance.iteration_count > 0:
            survey_key = f"{instance.id}/{instance.current_iteration or 1}"

        base_properties = [
            {
                "key": f"{SurveyEventProperties.SURVEY_DISMISSED}/{survey_key}",
                "value": "is_not_set",
                "operator": "is_not_set",
                "type": "person",
            },
            {
                "key": f"{SurveyEventProperties.SURVEY_RESPONDED}/{survey_key}",
                "value": "is_not_set",
                "operator": "is_not_set",
                "type": "person",
            },
        ]

        wait_period_days = None
        if instance.conditions and isinstance(instance.conditions, dict):
            wait_period_days = instance.conditions.get("seenSurveyWaitPeriodInDays")

        if wait_period_days is not None and wait_period_days > 0:
            user_submitted_dismissed_filter = {
                "groups": [
                    {
                        "variant": "",
                        "rollout_percentage": 100,
                        "properties": [
                            *base_properties,
                            {
                                "key": SurveyEventProperties.SURVEY_LAST_SEEN_DATE,
                                "value": "is_not_set",
                                "operator": "is_not_set",
                                "type": "person",
                            },
                        ],
                    },
                    {
                        "variant": "",
                        "rollout_percentage": 100,
                        "properties": [
                            *base_properties,
                            {
                                "key": SurveyEventProperties.SURVEY_LAST_SEEN_DATE,
                                "value": f"{int(wait_period_days)}d",
                                "operator": "is_date_before",
                                "type": "person",
                            },
                        ],
                    },
                ]
            }
        else:
            user_submitted_dismissed_filter = {
                "groups": [
                    {
                        "variant": "",
                        "rollout_percentage": 100,
                        "properties": base_properties,
                    }
                ]
            }

        if instance.internal_targeting_flag:
            existing_targeting_flag = instance.internal_targeting_flag
            # Note: new filters must come LAST to overwrite old iteration-unaware properties
            serialized_data_filters = {**existing_targeting_flag.filters, **user_submitted_dismissed_filter}

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
            # Ensure the request method is set correctly for validation
            if existing_flag:
                self.context["request"].method = "PATCH"
                existing_flag_serializer = FeatureFlagSerializer(
                    existing_flag,
                    data={"filters": filters},
                    partial=True,
                    context=self.context,
                )
                existing_flag_serializer.is_valid(raise_exception=True)
                return existing_flag_serializer.save()
            else:
                self.context["request"].method = "POST"
                random_id = generate("1234567890abcdef", 10)
                feature_flag_key = slugify(f"{SURVEY_TARGETING_FLAG_PREFIX}{random_id}{flag_name_suffix or ''}")
                feature_flag_serializer = FeatureFlagSerializer(
                    data={
                        "key": feature_flag_key,
                        "name": f"Targeting flag for survey {name}",
                        "filters": filters,
                        "active": active,
                        "creation_context": "surveys",
                    },
                    context=self.context,
                )

                feature_flag_serializer.is_valid(raise_exception=True)
                return feature_flag_serializer.save()


@extend_schema(tags=[ProductKey.SURVEYS])
class SurveyViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "survey"
    queryset = Survey.objects.select_related(
        "linked_flag", "linked_insight", "targeting_flag", "internal_targeting_flag"
    ).all()
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "description"]

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.request.method == "POST" or self.request.method == "PATCH":
            return SurveySerializerCreateUpdateOnly
        else:
            return SurveySerializer

    def safely_get_queryset(self, queryset):
        return queryset.exclude(product_tour__isnull=False)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        related_targeting_flag = instance.targeting_flag
        if related_targeting_flag:
            related_targeting_flag.delete()

        related_internal_targeting_flag = instance.internal_targeting_flag
        if related_internal_targeting_flag:
            related_internal_targeting_flag.delete()

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, self.request.user),
            was_impersonated=is_impersonated_session(request),
            item_id=instance.id,
            scope="Survey",
            activity="deleted",
            detail=Detail(name=instance.name),
        )

        return super().destroy(request, *args, **kwargs)

    def _get_partial_responses_filter(self, base_conditions_sql: list[str]) -> str:
        unique_uuids_subquery = get_unique_survey_event_uuids_sql_subquery(
            base_conditions_sql=base_conditions_sql,
        )

        return f"uuid IN {unique_uuids_subquery}"

    def _get_archived_responses_filter(self, survey_id: str | None = None) -> tuple[str, dict]:
        archived_uuids = get_archived_response_uuids(survey_id, self.team_id)

        if not archived_uuids:
            return "", {}

        params = {"archived_uuids": list(archived_uuids)}
        return "uuid NOT IN %(archived_uuids)s", params

    @action(methods=["GET"], detail=False, required_scopes=["survey:read"])
    def responses_count(self, request: request.Request, **kwargs):
        """Get response counts for all surveys.

        Args:
            exclude_archived: Optional boolean to exclude archived responses (default: false, includes archived)
            survey_ids: Optional comma-separated list of survey IDs to filter by

        Returns:
            Dictionary mapping survey IDs to response counts
        """
        exclude_archived = request.query_params.get("exclude_archived", "false").lower() == "true"
        survey_ids_param = request.query_params.get("survey_ids")

        earliest_survey_start_date = Survey.objects.filter(team__project_id=self.project_id).aggregate(
            Min("start_date")
        )["start_date__min"]

        if not earliest_survey_start_date:
            # If there are no surveys or none have a start date, there can be no responses.
            return Response({})

        params = {"team_id": self.team_id, "timestamp": earliest_survey_start_date}

        partial_responses_filter = self._get_partial_responses_filter(
            base_conditions_sql=[
                "team_id = %(team_id)s",
                "timestamp >= %(timestamp)s",
            ],
        )

        archived_filter = ""
        if exclude_archived:
            archived_filter_sql, archived_params = self._get_archived_responses_filter()
            if archived_filter_sql:
                archived_filter = f"AND {archived_filter_sql}"
                params.update(archived_params)

        survey_ids_filter = ""
        if survey_ids_param:
            survey_ids = [sid.strip() for sid in survey_ids_param.split(",") if sid.strip()]
            if survey_ids:
                survey_ids_filter = (
                    f"AND JSONExtractString(properties, '{SurveyEventProperties.SURVEY_ID}') IN %(survey_ids)s"
                )
                params["survey_ids"] = survey_ids

        query = f"""
            SELECT
                JSONExtractString(properties, '{SurveyEventProperties.SURVEY_ID}') as survey_id,
                count()
            FROM events
            WHERE
                team_id = %(team_id)s
                AND event = '{SurveyEventName.SENT}'
                AND timestamp >= %(timestamp)s
                AND {partial_responses_filter}
                {archived_filter}
                {survey_ids_filter}
            GROUP BY survey_id
        """

        data = sync_execute(query, params)

        counts = {}
        for survey_id, count in data:
            counts[survey_id] = count

        return Response(counts)

    def _validate_and_parse_dates(
        self, date_from: str | None, date_to: str | None
    ) -> tuple[datetime | None, datetime | None]:
        """Validate and parse date_from and date_to.

        Args:
            date_from: Optional ISO timestamp for start date with timezone info
            date_to: Optional ISO timestamp for end date with timezone info

        Returns:
            Tuple of (parsed_date_from, parsed_date_to) in UTC

        Raises:
            ValidationError: If dates are invalid or if date_from is after date_to
        """
        parsed_from = None
        parsed_to = None

        try:
            if date_from:
                parsed_from = datetime.fromisoformat(date_from).astimezone(UTC)

            if date_to:
                parsed_to = datetime.fromisoformat(date_to).astimezone(UTC)

            if parsed_from and parsed_to and parsed_from > parsed_to:
                raise exceptions.ValidationError("date_from must be before date_to")

            return parsed_from, parsed_to

        except ValueError:
            raise exceptions.ValidationError(
                "Invalid date format. Please use ISO 8601 format with timezone info (e.g. 2024-01-01T00:00:00Z or 2024-01-01T00:00:00+00:00)"
            )

    def _process_survey_results(
        self, results: list[tuple[str, int, int, datetime | None, datetime | None]]
    ) -> SurveyStats:
        """Process raw survey event results into stats format.

        Args:
            results: Raw results from ClickHouse query containing event stats

        Returns:
            Dictionary containing processed stats for each event type
        """
        # Initialize stats with zero values for all event types
        stats: SurveyStats = {
            SurveyEventName.SHOWN.value: {
                "total_count": 0,
                "unique_persons": 0,
                "first_seen": None,
                "last_seen": None,
                "unique_persons_only_seen": 0,  # Calculated later in _get_survey_stats
                "total_count_only_seen": 0,  # Calculated later in _get_survey_stats
            },
            SurveyEventName.DISMISSED.value: {
                "total_count": 0,
                "unique_persons": 0,
                "first_seen": None,
                "last_seen": None,
                # These fields are not applicable/calculated for dismissed/sent
                "unique_persons_only_seen": 0,
                "total_count_only_seen": 0,
            },
            SurveyEventName.SENT.value: {
                "total_count": 0,
                "unique_persons": 0,
                "first_seen": None,
                "last_seen": None,
                # These fields are not applicable/calculated for dismissed/sent
                "unique_persons_only_seen": 0,
                "total_count_only_seen": 0,
            },
        }

        # Update stats with actual results
        for event_name, total_count, unique_persons, first_seen, last_seen in results:
            event_stats: EventStats = {
                "total_count": total_count,
                "unique_persons": unique_persons,
                "first_seen": first_seen.isoformat() + "Z" if first_seen else None,
                "last_seen": last_seen.isoformat() + "Z" if last_seen else None,
                # Ensure these are initialized to 0
                "unique_persons_only_seen": 0,
                "total_count_only_seen": 0,
            }

            if event_name == SurveyEventName.SHOWN.value:
                stats[SurveyEventName.SHOWN.value] = event_stats
            elif event_name == SurveyEventName.DISMISSED.value:
                stats[SurveyEventName.DISMISSED.value] = event_stats
            elif event_name == SurveyEventName.SENT.value:
                stats[SurveyEventName.SENT.value] = event_stats

        # REMOVED calculation block for _only_seen fields from here.
        return stats

    def _calculate_rates(self, stats: SurveyStats) -> SurveyRates:
        """Calculate response and dismissal rates from stats.

        Args:
            stats: Dictionary containing event stats

        Returns:
            Dictionary containing calculated rates
        """
        rates: SurveyRates = {
            "response_rate": 0.0,
            "dismissal_rate": 0.0,
            "unique_users_response_rate": 0.0,
            "unique_users_dismissal_rate": 0.0,
        }

        shown_count = stats[SurveyEventName.SHOWN.value]["total_count"]
        if shown_count > 0:
            sent_count = stats[SurveyEventName.SENT.value]["total_count"]
            dismissed_count = stats[SurveyEventName.DISMISSED.value]["total_count"]
            unique_users_shown_count = stats[SurveyEventName.SHOWN.value]["unique_persons"]
            unique_users_sent_count = stats[SurveyEventName.SENT.value]["unique_persons"]
            unique_users_dismissed_count = stats[SurveyEventName.DISMISSED.value]["unique_persons"]
            rates = {
                "response_rate": round(sent_count / shown_count * 100, 2),
                "dismissal_rate": round(dismissed_count / shown_count * 100, 2),
                "unique_users_response_rate": round(unique_users_sent_count / unique_users_shown_count * 100, 2),
                "unique_users_dismissal_rate": round(unique_users_dismissed_count / unique_users_shown_count * 100, 2),
            }
        return rates

    def _get_survey_stats(
        self, date_from: str | None, date_to: str | None, survey_id: str | None = None, exclude_archived: bool = False
    ) -> dict:
        """Get survey statistics from ClickHouse.

        Args:
            date_from: Optional ISO timestamp for start date with timezone info
            date_to: Optional ISO timestamp for end date with timezone info
            survey_id: Optional survey ID to filter for. If None, gets stats for all surveys.
            exclude_archived: If True, exclude archived responses. Defaults to False (includes archived).

        Returns:
            Dictionary containing survey statistics and rates
        """
        parsed_from, parsed_to = self._validate_and_parse_dates(date_from, date_to)

        # Build query parameters
        params: dict[str, Any] = {"team_id": str(self.team_id)}
        date_filter = ""

        if parsed_from:
            date_filter += " AND timestamp >= %(date_from)s"
            params["date_from"] = parsed_from
        if parsed_to:
            date_filter += " AND timestamp <= %(date_to)s"
            params["date_to"] = parsed_to

        # Add archive filter if needed
        archive_filter = ""
        if survey_id and exclude_archived:
            archive_filter_sql, archive_params = self._get_archived_responses_filter(survey_id)
            if archive_filter_sql:
                archive_filter = f"AND {archive_filter_sql}"
                params.update(archive_params)

        # Add survey filter if specific survey
        survey_filter = ""
        if survey_id:
            survey_filter = f"AND JSONExtractString(properties, '{SurveyEventProperties.SURVEY_ID}') = %(survey_id)s"
            params["survey_id"] = str(survey_id)
        else:
            # For global stats, only include non-archived surveys
            active_survey_ids = list(
                Survey.objects.filter(team_id=self.team_id, archived=False).values_list("id", flat=True)
            )
            if not active_survey_ids:
                return {
                    "stats": {},
                    "rates": {
                        "response_rate": 0.0,
                        "dismissal_rate": 0.0,
                        "unique_users_response_rate": 0.0,
                        "unique_users_dismissal_rate": 0.0,
                    },
                }
            survey_filter = f"AND JSONExtractString(properties, '{SurveyEventProperties.SURVEY_ID}') IN %(survey_ids)s"
            params["survey_ids"] = [str(id) for id in active_survey_ids]

        partial_responses_filter = self._get_partial_responses_filter(
            base_conditions_sql=[
                "team_id = %(team_id)s",
            ],
        )

        # Query 1: Base Stats (Similar to original query)
        base_stats_query = f"""
            SELECT
                event as event_name,
                count() as total_count,
                count(DISTINCT person_id) as unique_persons,
                if(count() > 0, min(timestamp), null) as first_seen,
                if(count() > 0, max(timestamp), null) as last_seen
            FROM events
            WHERE team_id = %(team_id)s
            AND event IN (%(shown)s, %(dismissed)s, %(sent)s)
            {survey_filter}
            {date_filter}
            {archive_filter}
            AND (
                event != %(dismissed)s
                OR
                COALESCE(JSONExtractBool(properties, '{SurveyEventProperties.SURVEY_PARTIALLY_COMPLETED}'), False) = False
            )
            AND (
                event != %(sent)s
                OR
                {partial_responses_filter}
            )
            GROUP BY event
        """
        query_params = {
            **params,
            "shown": SurveyEventName.SHOWN.value,
            "dismissed": SurveyEventName.DISMISSED.value,
            "sent": SurveyEventName.SENT.value,
        }
        results_base = sync_execute(base_stats_query, query_params)

        # Query 2: Count of unique persons who both dismissed AND sent
        dismissed_and_sent_query = f"""
            SELECT count()
            FROM (
                SELECT person_id
                FROM events
                WHERE team_id = %(team_id)s
                  AND event IN (%(dismissed)s, %(sent)s)
                  {survey_filter}
                  {date_filter}
                  {archive_filter}
                AND (
                    event != %(dismissed)s
                    OR
                    COALESCE(JSONExtractBool(properties, '{SurveyEventProperties.SURVEY_PARTIALLY_COMPLETED}'), False) = False
                )
                GROUP BY person_id
                HAVING sum(if(event = %(dismissed)s, 1, 0)) > 0
                   AND sum(if(event = %(sent)s, 1, 0)) > 0
            ) AS PersonsWithBothEvents
        """
        dismissed_and_sent_count_result = sync_execute(dismissed_and_sent_query, query_params)
        dismissed_and_sent_count = dismissed_and_sent_count_result[0][0] if dismissed_and_sent_count_result else 0

        # Process initial stats
        stats = self._process_survey_results(results_base)

        # Adjust dismissed unique count
        if SurveyEventName.DISMISSED.value in stats:
            stats[SurveyEventName.DISMISSED.value]["unique_persons"] -= dismissed_and_sent_count
            # Ensure it doesn't go below zero, although logically it shouldn't
            stats[SurveyEventName.DISMISSED.value]["unique_persons"] = max(
                0, stats[SurveyEventName.DISMISSED.value]["unique_persons"]
            )

        # Recalculate derived 'only_seen' counts based on final counts
        if SurveyEventName.SHOWN.value in stats:
            # Get final counts, defaulting to 0 if a category has no events
            unique_shown = stats.get(SurveyEventName.SHOWN.value, {}).get("unique_persons", 0)
            unique_dismissed = stats.get(SurveyEventName.DISMISSED.value, {}).get(
                "unique_persons", 0
            )  # Use adjusted count
            unique_sent = stats.get(SurveyEventName.SENT.value, {}).get("unique_persons", 0)

            total_shown = stats.get(SurveyEventName.SHOWN.value, {}).get("total_count", 0)
            total_dismissed = stats.get(SurveyEventName.DISMISSED.value, {}).get("total_count", 0)
            total_sent = stats.get(SurveyEventName.SENT.value, {}).get("total_count", 0)

            # Calculate unique persons who only saw the survey
            stats[SurveyEventName.SHOWN.value]["unique_persons_only_seen"] = (
                unique_shown - unique_dismissed - unique_sent
            )
            stats[SurveyEventName.SHOWN.value]["unique_persons_only_seen"] = max(
                0, stats[SurveyEventName.SHOWN.value]["unique_persons_only_seen"]
            )

            # Calculate total count for those who only saw the survey
            stats[SurveyEventName.SHOWN.value]["total_count_only_seen"] = total_shown - total_dismissed - total_sent
            stats[SurveyEventName.SHOWN.value]["total_count_only_seen"] = max(
                0, stats[SurveyEventName.SHOWN.value]["total_count_only_seen"]
            )

        # Calculate rates using the adjusted stats
        rates = self._calculate_rates(stats)

        response_data = {
            "stats": stats,
            "rates": rates,
        }

        return response_data

    @action(methods=["GET"], detail=True, url_path="stats", required_scopes=["survey:read"])
    def survey_stats(self, request: request.Request, **kwargs) -> Response:
        """Get survey response statistics for a specific survey.

        Args:
            date_from: Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
            date_to: Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)
            exclude_archived: Optional boolean to exclude archived responses (default: false, includes archived)

        Returns:
            Survey statistics including event counts, unique respondents, and conversion rates
        """
        survey_id = kwargs["pk"]
        date_from = request.query_params.get("date_from", None)
        date_to = request.query_params.get("date_to", None)
        exclude_archived = request.query_params.get("exclude_archived", "false").lower() == "true"

        try:
            survey = self.get_object()
        except Survey.DoesNotExist:
            raise exceptions.NotFound("Survey not found")

        response_data = self._get_survey_stats(date_from, date_to, survey_id, exclude_archived)

        # Add survey metadata
        response_data["survey_id"] = survey_id
        response_data["start_date"] = survey.start_date
        response_data["end_date"] = survey.end_date

        return Response(response_data)

    @action(
        methods=["POST"],
        detail=True,
        url_path="responses/(?P<response_uuid>[^/]+)/archive",
        required_scopes=["survey:write"],
    )
    def archive_response(self, request: request.Request, response_uuid: str, **kwargs) -> Response:
        """Archive a single survey response."""
        survey = self.get_object()

        try:
            UUID(response_uuid)
        except ValueError:
            return Response({"detail": "Invalid UUID format"}, status=400)

        archive, created = SurveyResponseArchive.objects.get_or_create(
            team_id=self.team_id,
            survey=survey,
            response_uuid=response_uuid,
        )

        if created:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team_id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                item_id=survey.id,
                scope="Survey",
                activity="response_archived",
                detail=Detail(name=f"Response {response_uuid}"),
            )

        return Response(status.HTTP_200_OK)

    @action(
        methods=["POST"],
        detail=True,
        url_path="responses/(?P<response_uuid>[^/]+)/unarchive",
        required_scopes=["survey:write"],
    )
    def unarchive_response(self, request: request.Request, response_uuid: str, **kwargs) -> Response:
        """Unarchive a single survey response."""
        survey = self.get_object()

        try:
            UUID(response_uuid)
        except ValueError:
            return Response({"detail": "Invalid UUID format"}, status=400)

        deleted_count, _ = SurveyResponseArchive.objects.filter(
            team_id=self.team_id, survey=survey, response_uuid=response_uuid
        ).delete()

        if deleted_count > 0:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team_id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated_session(request),
                item_id=survey.id,
                scope="Survey",
                activity="response_unarchived",
                detail=Detail(name=f"Response {response_uuid}"),
            )

        return Response(status.HTTP_200_OK)

    @action(methods=["GET"], detail=True, url_path="archived-response-uuids", required_scopes=["survey:read"])
    def archived_response_uuids(self, request: request.Request, **kwargs) -> Response:
        """
        Get list of archived response UUIDs for HogQL filtering.

        Returns list of UUIDs that the frontend can use to filter out archived responses
        in HogQL queries.
        """
        survey = self.get_object()
        uuids = get_archived_response_uuids(str(survey.id), self.team_id)
        return Response(list(uuids))

    @action(methods=["GET"], detail=False, url_path="stats", required_scopes=["survey:read"])
    def global_stats(self, request: request.Request, **kwargs) -> Response:
        """Get aggregated response statistics across all surveys.

        Args:
            date_from: Optional ISO timestamp for start date (e.g. 2024-01-01T00:00:00Z)
            date_to: Optional ISO timestamp for end date (e.g. 2024-01-31T23:59:59Z)

        Returns:
            Aggregated statistics across all surveys including total counts and rates
        """
        date_from = request.query_params.get("date_from", None)
        date_to = request.query_params.get("date_to", None)

        response_data = self._get_survey_stats(date_from, date_to)
        return Response(response_data)

    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Survey", team_id=self.team_id, limit=limit, page=page)

        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]

        if not Survey.objects.filter(id=item_id, team__project_id=self.project_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="Survey",
            team_id=self.team_id,
            item_ids=[item_id],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["POST"], detail=True, required_scopes=["survey:read"])
    def summarize_responses(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        user = cast(User, request.user)

        survey_id = kwargs["pk"]

        if not Survey.objects.filter(id=survey_id, team__project_id=self.project_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        survey = self.get_object()

        try:
            question_index_param = request.query_params.get("question_index", None)
            question_index = int(question_index_param) if question_index_param else None
        except (ValueError, TypeError):
            question_index = None

        question_id = request.query_params.get("question_id", None)

        if question_index is None and question_id is None:
            raise exceptions.ValidationError("question_index or question_id is required")

        # Check for force_refresh flag in request body
        force_refresh = request.data.get("force_refresh", False)

        # Check for cached summary in question_summaries field
        if not force_refresh and question_id and survey.question_summaries:
            cached_summary = survey.question_summaries.get(question_id)
            if cached_summary:
                return Response(
                    {
                        "content": cached_summary.get("summary", ""),
                        "response_count": cached_summary.get("responseCount", 0),
                        "generated_at": cached_summary.get("generatedAt"),
                        "trace_id": cached_summary.get("traceId"),
                        "cached": True,
                    }
                )

        # Short-term Redis cache for rapid repeated requests
        cache_key = f"summarize_survey_responses_{self.team.pk}_{self.kwargs['pk']}_{question_id or question_index}"
        cached_response = cache.get(cache_key)
        if cached_response is not None and not force_refresh:
            return Response(cached_response)

        environment_is_allowed = settings.DEBUG or is_cloud()
        has_gemini_api_key = bool(settings.GEMINI_API_KEY)
        if not environment_is_allowed or not has_gemini_api_key:
            raise exceptions.ValidationError("survey summary is only supported in PostHog Cloud")

        end_date: datetime = (survey.end_date or datetime.now()).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        # Extract the question text and choices from the survey
        question_text = None
        question_choices = None
        if survey.questions and question_id:
            # Find the question with the matching ID
            for question in survey.questions:
                if question.get("id", None) == question_id:
                    question_text = question.get("question")
                    question_choices = question.get("choices")
                    break
        elif survey.questions and question_index is not None:
            # Fallback to question index if question_id is not provided
            if 0 <= question_index < len(survey.questions):
                question_text = survey.questions[question_index].get("question")
                question_choices = survey.questions[question_index].get("choices")

        if question_text is None:
            raise exceptions.ValidationError("the text of the question is required")

        # Fetch responses using the new module
        # For choice questions, exclude predefined choices to only get open-ended "Other" responses
        responses = fetch_responses(
            survey_id=survey_id,
            question_index=question_index,
            question_id=question_id,
            start_date=(survey.start_date or survey.created_at).replace(hour=0, minute=0, second=0, microsecond=0),
            end_date=end_date,
            team=self.team,
            exclude_values=question_choices,
        )
        response_count = len(responses)

        if not responses:
            return Response(
                {
                    "content": "No responses to analyze.",
                    "response_count": 0,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "cached": False,
                }
            )

        # Generate summary using Gemini
        try:
            result = summarize_responses(
                question_text,
                responses,
                distinct_id=str(user.distinct_id),
                survey_id=str(survey_id),
                question_id=question_id,
                team_id=self.team.pk,
            )
            content = format_as_markdown(result.summary)
            trace_id = result.trace_id
        except exceptions.ValidationError:
            raise
        except exceptions.APIException:
            raise
        except Exception as e:
            logger.exception(
                "Failed to generate survey summary",
                survey_id=survey_id,
                question_id=question_id,
                error_type=type(e).__name__,
                error=str(e),
            )
            raise exceptions.APIException("Failed to generate summary. Please try again.")

        generated_at = datetime.now(UTC).isoformat()

        # Prepare response data
        response_data = {
            "content": content,
            "response_count": response_count,
            "generated_at": generated_at,
            "trace_id": trace_id,
            "cached": False,
        }

        # Save to question_summaries field for long-term caching
        if question_id:
            if survey.question_summaries is None:
                survey.question_summaries = {}
            survey.question_summaries[question_id] = {
                "summary": content,
                "responseCount": response_count,
                "generatedAt": generated_at,
                "traceId": trace_id,
            }
            survey.save(update_fields=["question_summaries"])

        # Short-term Redis cache
        cache.set(cache_key, response_data, timeout=30)

        posthoganalytics.capture(
            event="survey response summarized",
            distinct_id=str(user.distinct_id),
            properties={"survey_id": survey_id, "question_id": question_id, "response_count": response_count},
        )

        # let the browser cache for half the time we cache on the server
        return Response(response_data, headers={"Cache-Control": "max-age=15"})

    @action(methods=["POST"], detail=True, url_path="summary_headline", required_scopes=["survey:read"])
    def summary_headline(self, request: request.Request, **kwargs):
        survey_id = kwargs["pk"]
        logger.info("[summary_headline] request received", survey_id=survey_id)

        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        user = cast(User, request.user)

        logger.info("[summary_headline] checking survey exists", survey_id=survey_id)
        if not Survey.objects.filter(id=survey_id, team__project_id=self.project_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        logger.info("[summary_headline] fetching survey", survey_id=survey_id)
        survey = self.get_object()
        logger.info("[summary_headline] survey fetched", survey_id=survey_id)
        force_refresh = request.data.get("force_refresh", False)

        if not force_refresh and survey.headline_summary and survey.headline_response_count:
            return Response(
                {
                    "headline": survey.headline_summary,
                    "responses_sampled": survey.headline_response_count,
                    "has_more": False,
                }
            )

        if not self.team.organization.is_ai_data_processing_approved:
            return Response(
                {"error": "AI data processing must be approved to generate summaries"},
                status=status.HTTP_403_FORBIDDEN,
            )

        logger.info("[summary_headline] calling generate_survey_headline", survey_id=survey_id)
        result = generate_survey_headline(
            survey=survey,
            team=self.team,
            user=user,
        )

        timings_header = result.pop("timings_header", None)

        survey.headline_summary = result.get("headline")
        survey.headline_response_count = result.get("responses_sampled", 0)
        survey.save(update_fields=["headline_summary", "headline_response_count"])

        posthoganalytics.capture(
            event="survey headline generated",
            distinct_id=str(user.distinct_id),
            properties={
                "survey_id": survey_id,
                "responses_sampled": result.get("responses_sampled", 0),
                "has_more": result.get("has_more", False),
            },
        )

        r = Response(result)
        if timings_header:
            r.headers["Server-Timing"] = timings_header
        return r

    @action(methods=["POST"], detail=True, required_scopes=["survey:write"])
    def duplicate_to_projects(self, request: request.Request, **kwargs):
        """Duplicate a survey to multiple projects in a single transaction.

        Accepts a list of target team IDs and creates a copy of the survey in each project.
        Uses an all-or-nothing approach - if any duplication fails, all changes are rolled back.
        """
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        user = cast(User, request.user)
        survey_id = kwargs["pk"]

        if not Survey.objects.filter(id=survey_id, team__project_id=self.project_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        source_survey = self.get_object()
        target_team_ids = request.data.get("target_team_ids", [])

        if not target_team_ids or not isinstance(target_team_ids, list):
            raise exceptions.ValidationError("target_team_ids must be a non-empty list of team IDs")

        user_organization = user.organization
        if not user_organization:
            raise exceptions.ValidationError("User must belong to an organization")

        target_teams = Team.objects.filter(id__in=target_team_ids, organization_id=user_organization.id)

        if len(target_teams) != len(target_team_ids):
            raise exceptions.ValidationError("One or more target teams not found or you don't have access to them")

        duplicate_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        created_surveys = []

        try:
            with transaction.atomic():
                # Validate all survey data first
                surveys_to_create = []
                for team in target_teams:
                    cleaned_conditions = None
                    if source_survey.conditions:
                        cleaned_conditions = dict(source_survey.conditions)
                        # Remove project-specific fields: flags, actions, and events don't transfer across projects
                        cleaned_conditions.pop("linkedFlagVariant", None)
                        cleaned_conditions.pop("actions", None)
                        cleaned_conditions.pop("events", None)

                    survey_data = {
                        "name": f"{source_survey.name} (duplicated at {duplicate_timestamp})",
                        "description": source_survey.description,
                        "type": source_survey.type,
                        "questions": [
                            {k: v for k, v in q.items() if k != "id"} for q in (source_survey.questions or [])
                        ],
                        "appearance": source_survey.appearance,
                        "conditions": cleaned_conditions,
                        "archived": False,
                        "start_date": None,
                        "end_date": None,
                        "responses_limit": source_survey.responses_limit,
                        "iteration_count": source_survey.iteration_count,
                        "iteration_frequency_days": source_survey.iteration_frequency_days,
                        "schedule": source_survey.schedule,
                        "enable_partial_responses": source_survey.enable_partial_responses,
                    }
                    # NOTE: linked_flag_id, targeting_flag, and internal flags are intentionally omitted
                    # as they are project-specific and don't exist in other projects

                    serializer = SurveySerializerCreateUpdateOnly(
                        data=survey_data,
                        context={
                            "request": request,
                            "team_id": team.id,
                            "project_id": team.project_id,
                        },
                    )

                    serializer.is_valid(raise_exception=True)

                    # Build Survey instance from validated data
                    new_survey = Survey(
                        team=team,
                        created_by=user,
                        **serializer.validated_data,
                    )
                    surveys_to_create.append(new_survey)

                for survey in surveys_to_create:
                    ensure_question_ids(survey)

                # Bulk create all surveys
                created_survey_objects = Survey.objects.bulk_create(surveys_to_create)

                # Prepare response data and activity logs
                for created_survey in created_survey_objects:
                    created_surveys.append(
                        {
                            "team_id": created_survey.team_id,
                            "survey_id": str(created_survey.id),
                            "name": created_survey.name,
                        }
                    )

                    log_activity(
                        organization_id=user_organization.id,
                        team_id=created_survey.team_id,
                        user=user,
                        was_impersonated=is_impersonated_session(request),
                        item_id=created_survey.id,
                        scope="Survey",
                        activity="created",
                        detail=Detail(
                            name=created_survey.name,
                            changes=[
                                Change(
                                    type="Survey",
                                    action="created",
                                    field="source_survey_id",
                                    after=str(survey_id),
                                )
                            ],
                        ),
                    )

        except exceptions.ValidationError as e:
            structlog.get_logger(__name__).error(
                "bulk_survey_duplication_validation_error",
                error=str(e),
                error_detail=e.detail if hasattr(e, "detail") else None,
                survey_id=survey_id,
                user_id=user.id,
                target_team_ids=target_team_ids,
            )
            raise
        except Exception as e:
            structlog.get_logger(__name__).error(
                "bulk_survey_duplication_error",
                error=str(e),
                error_type=type(e).__name__,
                survey_id=survey_id,
                user_id=user.id,
                target_team_ids=target_team_ids,
            )
            capture_exception(e)
            raise exceptions.ValidationError(
                {
                    "error": "Bulk duplication failed due to an unexpected error",
                }
            )

        posthoganalytics.capture(
            event="survey bulk duplicated",
            distinct_id=str(user.distinct_id),
            properties={
                "source_survey_id": str(survey_id),
                "target_count": len(created_surveys),
                "target_team_ids": target_team_ids,
            },
        )

        return Response(
            {
                "created_surveys": created_surveys,
                "count": len(created_surveys),
            },
            status=status.HTTP_201_CREATED,
        )


class SurveyConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["survey_config"]


class SurveyAPIActionSerializer(serializers.ModelSerializer):
    steps = ActionStepJSONSerializer(many=True, required=False)

    class Meta:
        model = Action
        fields = [
            "id",
            "name",
            "steps",
        ]
        read_only_fields = fields


class SurveyAPISerializer(serializers.ModelSerializer):
    """
    Serializer for the exposed /api/surveys endpoint, to be used in posthog-js and for headless APIs.
    """

    linked_flag_key = serializers.CharField(source="linked_flag.key", read_only=True)
    targeting_flag_key = serializers.CharField(source="targeting_flag.key", read_only=True)
    internal_targeting_flag_key = serializers.CharField(source="internal_targeting_flag.key", read_only=True)
    conditions = serializers.SerializerMethodField(method_name="get_conditions")
    enable_partial_responses = serializers.BooleanField(read_only=True)

    class Meta:
        model = Survey
        fields = [
            "id",
            "name",
            # NB: The "description" field is serialized on Create/Update request, and used to be serialized on the next line,
            # But we had a user write in complaining that we were exposing the description in the API
            # (https://posthoghelp.zendesk.com/agent/tickets/15210), which was a problem for them
            # since they were using it as a way to store sensitive information. Given that we don't ever use
            # that field to render the survey, we can safely remove it from the API response.
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
            "current_iteration_start_date",
            "schedule",
            "enable_partial_responses",
        ]
        read_only_fields = fields

    def get_conditions(self, survey: Survey):
        return get_survey_conditions_with_actions(survey, SurveyAPIActionSerializer)


def get_surveys_opt_in(team: Team) -> bool:
    # return False if the team has not set a value for surveys_opt_in
    if team.surveys_opt_in is None:
        return False
    return team.surveys_opt_in


def get_surveys_count(team: Team) -> int:
    return (
        Survey.objects.db_manager(READ_DB_FOR_SURVEYS)
        .filter(team__project_id=team.project_id)
        .exclude(archived=True)
        .count()
    )


def get_surveys_response(team: Team):
    surveys = SurveyAPISerializer(
        Survey.objects.db_manager(READ_DB_FOR_SURVEYS)
        .filter(team__project_id=team.project_id)
        .exclude(archived=True)
        .select_related("linked_flag", "targeting_flag", "internal_targeting_flag")
        .prefetch_related("actions"),
        many=True,
    ).data

    serialized_survey_config: dict[str, Any] = {}
    if team.survey_config is not None:
        serialized_survey_config = SurveyConfigSerializer(team).data

    return {
        "surveys": surveys,
        "survey_config": serialized_survey_config.get("survey_config", None),
    }


@csrf_exempt
def surveys(request: Request):
    token = get_token(None, request)
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

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

    hypercache_response = None
    response = None

    if settings.SURVEYS_API_USE_HYPERCACHE_TOKENS and (
        "*" in settings.SURVEYS_API_USE_HYPERCACHE_TOKENS or token in settings.SURVEYS_API_USE_HYPERCACHE_TOKENS
    ):
        try:
            hypercache_response = surveys_hypercache.get_from_cache(token)
            if not hypercache_response:
                raise Exception("No hypercache response found")

            COUNTER_SURVEYS_API_USE_REMOTE_CONFIG.labels(result="found").inc()
            response = hypercache_response

        except Team.DoesNotExist:
            COUNTER_SURVEYS_API_USE_REMOTE_CONFIG.labels(result="not_found").inc()
            pass
        except Exception as e:
            capture_exception(e)
            COUNTER_SURVEYS_API_USE_REMOTE_CONFIG.labels(result="error").inc()
            pass  # For now fallback

    # If we didn't get a hypercache response or we are comparing then load the normal response to compare
    if not hypercache_response or settings.SURVEYS_API_USE_REMOTE_CONFIG_COMPARE:
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
        response = get_surveys_response(team)

        if hypercache_response:
            # Do the comparison here
            try:
                if hypercache_response == response:
                    COUNTER_SURVEYS_API_REMOTE_CONFIG_COMPARISON.labels(result="same").inc()
                else:
                    COUNTER_SURVEYS_API_REMOTE_CONFIG_COMPARISON.labels(result="different").inc()
                    logger.warning(
                        "SurveyHypercacheResponseDifferentFromAPIResponse",
                        hypercache_response=hypercache_response,
                        response=response,
                    )

            except Exception as e:
                capture_exception(e)

    return cors_response(request, JsonResponse(response))


@csrf_exempt
@axes_dispatch
def public_survey_page(request, survey_id: str):
    """
    Server-side rendered public survey page with security and performance optimizations
    """
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

    # Input validation
    if not UUIDT.is_valid_uuid(survey_id):
        logger.warning("survey_page_invalid_id", survey_id=survey_id)
        return render(
            request,
            "surveys/error.html",
            {
                "error_title": "Invalid request",
                "error_message": "The requested survey is not available.",
            },
            status=400,
        )

    # Database query with minimal fields and timeout protection
    try:
        survey = Survey.objects.select_related("team").get(id=survey_id)
    except Survey.DoesNotExist:
        logger.info("survey_page_not_found", survey_id=survey_id)
        # Use generic error message to prevent survey ID enumeration
        return render(
            request,
            "surveys/error.html",
            {
                "error_title": "Survey not available",
                "error_message": "The requested survey is not available.",
            },
            status=404,
        )
    except Exception as e:
        logger.exception("survey_page_db_error", error=str(e), survey_id=survey_id)
        capture_exception(e)
        return render(
            request,
            "surveys/error.html",
            {
                "error_title": "Service unavailable",
                "error_message": "The service is temporarily unavailable. Please try again later.",
            },
            status=503,
        )

    survey_is_running = (
        survey.start_date is not None and survey.start_date <= datetime.now(UTC) and survey.end_date is None
    )

    # Check survey availability (combine checks for consistent error message)
    if survey.archived or survey.type != Survey.SurveyType.EXTERNAL_SURVEY or not survey_is_running:
        logger.info(
            "survey_page_access_denied",
            survey_id=survey_id,
            archived=survey.archived,
            survey_type=survey.type,
        )
        return render(
            request,
            "surveys/error.html",
            {
                "error_title": "Survey not receiving responses",
                "error_message": "The requested survey is not receiving responses.",
            },
            status=404,  # Use 404 instead of 403 to prevent information leakage
        )

    # Build project config
    project_config = {
        "api_host": request.build_absolute_uri("/").rstrip("/"),
        "token": survey.team.api_token,
    }

    if hasattr(survey.team, "ui_host") and survey.team.ui_host:
        project_config["ui_host"] = survey.team.ui_host

    serializer = SurveyAPISerializer(survey)
    survey_data = serializer.data
    context = {
        "name": survey.name,
        "survey_data": survey_data,
        "project_config": project_config,
        "debug": settings.DEBUG,
    }

    logger.info("survey_page_rendered", survey_id=survey_id, team_id=survey.team.id)

    response = render(request, "surveys/public_survey.html", context)

    response["X-Frame-Options"] = "DENY"  # Override global SAMEORIGIN to prevent iframe embedding
    # Cache headers
    response["Cache-Control"] = f"public, max-age={CACHE_TIMEOUT_SECONDS}"
    response["Vary"] = "Accept-Encoding"  # Enable compression caching

    return response


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
        raise


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
