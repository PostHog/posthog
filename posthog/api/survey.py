from contextlib import contextmanager
from typing import Any, cast
from urllib.parse import urlparse

import nh3
from django.db.models import Min
from django.http import JsonResponse, HttpResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from nanoid import generate
from rest_framework import request, serializers, status, viewsets
from posthog.api.utils import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.action import ActionSerializer
from posthog.api.feature_flag import (
    BEHAVIOURAL_COHORT_FOUND_ERROR_CODE,
    FeatureFlagSerializer,
    MinimalFeatureFlagSerializer,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_token
from posthog.client import sync_execute
from posthog.models import Action
from posthog.constants import AvailableFeature
from posthog.exceptions import generate_exception_response
from posthog.models.activity_logging.activity_log import Change, changes_between, load_activity, log_activity, Detail
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feedback.survey import Survey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.utils_cors import cors_response
from loginas.utils import is_impersonated_session

SURVEY_TARGETING_FLAG_PREFIX = "survey-targeting-"
ALLOWED_LINK_URL_SCHEMES = ["https", "mailto"]


class SurveySerializer(serializers.ModelSerializer):
    linked_flag_id = serializers.IntegerField(required=False, allow_null=True, source="linked_flag.id")
    linked_flag = MinimalFeatureFlagSerializer(read_only=True)
    targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    internal_targeting_flag = MinimalFeatureFlagSerializer(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    conditions = serializers.SerializerMethodField(method_name="get_conditions", read_only=True)

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

    def get_conditions(self, survey: Survey):
        actions = survey.actions.all()
        if len(actions) > 0:
            # actionNames can change between when the survey is created and when its retrieved.
            # update the actionNames in the response from the real names of the actions as defined
            # in data management.
            survey.conditions["actions"] = {"values": ActionSerializer(actions, many=True).data}
        return survey.conditions


class SurveySerializerCreateUpdateOnly(serializers.ModelSerializer):
    linked_flag = MinimalFeatureFlagSerializer(read_only=True)
    linked_flag_id = serializers.IntegerField(required=False, write_only=True, allow_null=True)
    targeting_flag_id = serializers.IntegerField(required=False, write_only=True)
    targeting_flag_filters = serializers.JSONField(required=False, write_only=True, allow_null=True)
    remove_targeting_flag = serializers.BooleanField(required=False, write_only=True, allow_null=True)
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

        thank_you_description_content_type = value.get("thankYouMessageDescriptionContentType")
        if thank_you_description_content_type and thank_you_description_content_type not in ["text", "html"]:
            raise serializers.ValidationError("thankYouMessageDescriptionContentType must be one of ['text', 'html']")

        use_survey_html_descriptions = self.context["request"].user.organization.is_feature_available(
            AvailableFeature.SURVEYS_TEXT_HTML
        )

        if thank_you_description_content_type == "html" and not use_survey_html_descriptions:
            raise serializers.ValidationError(
                "You need to upgrade to PostHog Enterprise to use HTML in survey thank you message"
            )

        survey_popup_delay_seconds = value.get("surveyPopupDelaySeconds")
        if survey_popup_delay_seconds and survey_popup_delay_seconds < 0:
            raise serializers.ValidationError("Survey popup delay seconds must be a positive integer")

        return value

    def validate_conditions(self, value):
        if value is None:
            return value

        actions = value.get("actions")
        if actions is None:
            return value

        values = actions.get("values")
        if values is None or len(values) == 0:
            return value

        action_ids = (value.get("id") for value in values)
        project_actions = Action.objects.filter(team_id=self.context["team_id"], id__in=action_ids)

        for project_action in project_actions:
            for step in project_action.steps:
                if step.properties is not None and len(step.properties) > 0:
                    raise serializers.ValidationError(
                        "Survey cannot be activated by an Action with property filters defined on it."
                    )

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

            use_survey_html_descriptions = self.context["request"].user.organization.is_feature_available(
                AvailableFeature.SURVEYS_TEXT_HTML
            )

            if description_content_type == "html" and not use_survey_html_descriptions:
                raise serializers.ValidationError(
                    "You need to upgrade to PostHog Enterprise to use HTML in survey questions"
                )

            choices = raw_question.get("choices")
            if choices:
                if not isinstance(choices, list):
                    raise serializers.ValidationError("Question choices must be a list of strings")
                if any(not choice.strip() for choice in choices):
                    raise serializers.ValidationError("Question choices cannot be empty")

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
        self._associate_actions(instance, validated_data.get("conditions"))

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

        iteration_count = validated_data.get("iteration_count")
        if (
            instance.current_iteration is not None
            and iteration_count is not None
            and instance.current_iteration > iteration_count > 0
        ):
            raise serializers.ValidationError(
                f"Cannot change survey recurrence to {iteration_count}, should be at least {instance.current_iteration}"
            )

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

        self._add_user_survey_interacted_filters(instance, end_date)
        self._associate_actions(instance, validated_data.get("conditions"))
        return instance

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

        instance.actions.set(Action.objects.filter(team_id=self.context["team_id"], id__in=action_ids))
        instance.save()

    def _add_user_survey_interacted_filters(self, instance: Survey, end_date=None):
        survey_key = f"{instance.id}"
        if instance.iteration_count is not None and instance.iteration_count > 0:
            survey_key = f"{instance.id}/{instance.current_iteration or 1}"

        user_submitted_dismissed_filter = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": [
                        {
                            "key": f"$survey_dismissed/{survey_key}",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                            "type": "person",
                        },
                        {
                            "key": f"$survey_responded/{survey_key}",
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

    @action(methods=["GET"], detail=False)
    def responses_count(self, request: request.Request, **kwargs):
        earliest_survey_start_date = Survey.objects.filter(team_id=self.team_id).aggregate(Min("start_date"))[
            "start_date__min"
        ]
        data = sync_execute(
            f"""
            SELECT JSONExtractString(properties, '$survey_id') as survey_id, count()
            FROM events
            WHERE event = 'survey sent' AND team_id = %(team_id)s AND timestamp >= %(timestamp)s
            GROUP BY survey_id
        """,
            {"team_id": self.team_id, "timestamp": earliest_survey_start_date},
        )

        counts = {}
        for survey_id, count in data:
            counts[survey_id] = count

        return Response(counts)

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

        if not Survey.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="Survey",
            team_id=self.team_id,
            item_ids=[item_id],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)


class SurveyAPISerializer(serializers.ModelSerializer):
    """
    Serializer for the exposed /api/surveys endpoint, to be used in posthog-js and for headless APIs.
    """

    linked_flag_key = serializers.CharField(source="linked_flag.key", read_only=True)
    targeting_flag_key = serializers.CharField(source="targeting_flag.key", read_only=True)
    internal_targeting_flag_key = serializers.CharField(source="internal_targeting_flag.key", read_only=True)
    conditions = serializers.SerializerMethodField(method_name="get_conditions")

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
        ]
        read_only_fields = fields

    def get_conditions(self, survey: Survey):
        actions = survey.actions.all()
        if len(actions) > 0:
            # action names can change between when the survey is created and when its retrieved.
            # update the actionNames in the response from the real names of the actions as defined
            # in data management.
            if survey.conditions is None:
                survey.conditions = {}

            survey.conditions["actions"] = {"values": ActionSerializer(actions, many=True).data}
        return survey.conditions


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
        .select_related("linked_flag", "targeting_flag", "internal_targeting_flag")
        .prefetch_related("actions"),
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
