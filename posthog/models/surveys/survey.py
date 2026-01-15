import json
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from dateutil.rrule import DAILY, rrule
from django_deprecate_fields import deprecate_field

from posthog.models import Action
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.storage.hypercache import HyperCache

# we have seen users accidentally set a huge value for iteration count
# and cause performance issues, so we are extra careful with this value
# NB this is enforced in the UI too
MAX_ITERATION_COUNT = 500

if TYPE_CHECKING:
    from posthog.models.team import Team


class Survey(FileSystemSyncMixin, RootTeamMixin, UUIDTModel):
    class SurveyType(models.TextChoices):
        POPOVER = "popover", "popover"
        WIDGET = "widget", "widget"
        EXTERNAL_SURVEY = "external_survey", "external survey"
        API = "api", "api"

    class SurveySamplingIntervalType(models.TextChoices):
        DAY = "day", "day"
        WEEK = "week", "week"
        MONTH = "month", "month"

    class Schedule(models.TextChoices):
        ONCE = "once", "once"
        RECURRING = "recurring", "recurring"
        ALWAYS = "always", "always"

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "name"], name="unique survey name for team")]

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="surveys",
        related_query_name="survey",
    )
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True)
    linked_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_linked_flag",
        related_query_name="survey_linked_flag",
    )
    targeting_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_targeting_flag",
        related_query_name="survey_targeting_flag",
    )
    linked_insight = models.ForeignKey(
        "posthog.Insight",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_linked_insight",
        related_query_name="survey_linked_insight",
        db_index=True,
        db_constraint=True,
    )
    internal_targeting_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_internal_targeting_flag",
        related_query_name="survey_internal_targeting_flag",
    )
    internal_response_sampling_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_internal_response_sampling_flag",
        related_query_name="surveys_internal_response_sampling_flag",
    )
    type = models.CharField(max_length=40, choices=SurveyType.choices)
    conditions = models.JSONField(blank=True, null=True)
    questions = models.JSONField(
        blank=True,
        null=True,
        help_text="""
        The `array` of questions included in the survey. Each question must conform to one of the defined question types: Basic, Link, Rating, or Multiple Choice.

        Basic (open-ended question)
        - `id`: The question ID
        - `type`: `open`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `branching`: Branching logic for the question. See branching types below for details.

        Link (a question with a link)
        - `id`: The question ID
        - `type`: `link`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `link`: The URL associated with the question.
        - `branching`: Branching logic for the question. See branching types below for details.

        Rating (a question with a rating scale)
        - `id`: The question ID
        - `type`: `rating`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `display`: Display style of the rating (`number` or `emoji`).
        - `scale`: The scale of the rating (`number`).
        - `lowerBoundLabel`: Label for the lower bound of the scale.
        - `upperBoundLabel`: Label for the upper bound of the scale.
        - `isNpsQuestion`: Whether the question is an NPS rating.
        - `branching`: Branching logic for the question. See branching types below for details.

        Multiple choice
        - `id`: The question ID
        - `type`: `single_choice` or `multiple_choice`
        - `question`: The text of the question.
        - `description`: Optional description of the question.
        - `descriptionContentType`: Content type of the description (`html` or `text`).
        - `optional`: Whether the question is optional (`boolean`).
        - `buttonText`: Text displayed on the submit button.
        - `choices`: An array of choices for the question.
        - `shuffleOptions`: Whether to shuffle the order of the choices (`boolean`).
        - `hasOpenChoice`: Whether the question allows an open-ended response (`boolean`).
        - `branching`: Branching logic for the question. See branching types below for details.

        Branching logic can be one of the following types:

        Next question: Proceeds to the next question
        ```json
        {
            "type": "next_question"
        }
        ```

        End: Ends the survey, optionally displaying a confirmation message.
        ```json
        {
            "type": "end"
        }
        ```

        Response-based: Branches based on the response values. Available for the `rating` and `single_choice` question types.
        ```json
        {
            "type": "response_based",
            "responseValues": {
                "responseKey": "value"
            }
        }
        ```

        Specific question: Proceeds to a specific question by index.
        ```json
        {
            "type": "specific_question",
            "index": 2
        }
        ```

        Translations: Each question can include inline translations.
        - `translations`: Object mapping language codes to translated fields.
        - Language codes: ISO 639-1 ("es", "fr") or BCP 47 ("es-MX", "en-US")
        - Translatable fields: `question`, `description`, `buttonText`, `choices`, `lowerBoundLabel`, `upperBoundLabel`, `link`

        Example with translations:
        ```json
        {
            "id": "uuid",
            "type": "rating",
            "question": "How satisfied are you?",
            "lowerBoundLabel": "Not satisfied",
            "upperBoundLabel": "Very satisfied",
            "translations": {
                "es": {
                    "question": "¿Qué tan satisfecho estás?",
                    "lowerBoundLabel": "No satisfecho",
                    "upperBoundLabel": "Muy satisfecho"
                },
                "fr": {
                    "question": "Dans quelle mesure êtes-vous satisfait?"
                }
            }
        }
        ```
        """,
    )
    appearance = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="surveys",
        related_query_name="survey",
        null=True,
    )
    start_date = models.DateTimeField(null=True)
    end_date = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)
    # It's not a strict limit as it's enforced in a periodic task
    responses_limit = models.PositiveIntegerField(null=True)

    response_sampling_start_date = models.DateTimeField(null=True, blank=True)
    response_sampling_interval_type = models.CharField(
        null=True,
        blank=True,
        max_length=6,
        choices=SurveySamplingIntervalType.choices,
        default=SurveySamplingIntervalType.WEEK,
    )
    response_sampling_interval = models.PositiveIntegerField(null=True)
    # Upper limit of responses that should be accepted in a given response sampling interval.
    response_sampling_limit = models.PositiveIntegerField(null=True)
    # { 'daily_limits' : [{'date': <Date> , 'limit': <number of expected responses by this day>'}]
    response_sampling_daily_limits = models.JSONField(null=True)

    iteration_count = models.PositiveIntegerField(null=True)
    iteration_frequency_days = models.PositiveIntegerField(null=True)
    iteration_start_dates = ArrayField(
        base_field=models.DateTimeField(null=True),
        blank=True,
        default=None,
        null=True,
        size=None,
    )
    current_iteration = models.PositiveIntegerField(null=True)
    current_iteration_start_date = models.DateTimeField(null=True)
    schedule = models.CharField(
        max_length=40,
        choices=Schedule.choices,
        default=Schedule.ONCE,
        null=True,
        blank=True,
    )
    enable_partial_responses = models.BooleanField(default=False, null=True)

    # Allow hosted surveys to be embedded in iframes (removes X-Frame-Options header)
    enable_iframe_embedding = models.BooleanField(default=False)

    # AI-generated headline summary
    headline_summary = models.TextField(blank=True, null=True)
    headline_response_count = models.PositiveIntegerField(null=True, blank=True)

    # AI-generated per-question summaries
    # Format: { [questionId]: { summary: string, responseCount: number, generatedAt: string } }
    question_summaries = models.JSONField(blank=True, null=True)

    # Translations for multi-language support
    # Format: { [languageCode]: { name: string, description: string, ... } }
    # Language codes: ISO 639-1 ("es", "fr") or BCP 47 ("es-MX", "en-US")
    translations = models.JSONField(blank=True, null=True)

    # Use the survey_type instead. If it's external_survey, it's publicly shareable.
    is_publicly_shareable = deprecate_field(
        models.BooleanField(
            null=True,
            blank=True,
            help_text="Allow this survey to be accessed via public URL (https://app.posthog.com/surveys/[survey_id]) without authentication",
        ),
    )

    actions = models.ManyToManyField(Action)

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["Survey"]:
        base_qs = cls.objects.filter(team=team)
        return cls._filter_unfiled_queryset(base_qs, team, type="survey", ref_field="id")

    @classmethod
    def get_internal_flag_ids(
        cls,
        *,
        team_id: int | None = None,
        project_id: int | None = None,
        using: str = "default",
    ) -> set[int]:
        """
        Get IDs of all internally-managed survey flags.

        These flags (targeting_flag, internal_targeting_flag, internal_response_sampling_flag)
        are auto-generated for surveys and use operators not supported by local evaluation.
        They should be excluded from certain operations like local evaluation and flag lists.
        See GitHub issue #43631.

        Note: The user-created `linked_flag` is NOT included since it's user-managed.

        Args:
            team_id: Filter by team ID (use for team-scoped queries)
            project_id: Filter by project ID (use for project-scoped queries)
            using: Database alias to use (e.g., "default" or "replica")

        Returns:
            Set of feature flag IDs linked to surveys
        """
        if team_id is not None:
            queryset = cls.objects.db_manager(using).filter(team_id=team_id)
        elif project_id is not None:
            queryset = cls.objects.db_manager(using).filter(team__project_id=project_id)
        else:
            raise ValueError("Either team_id or project_id must be provided")

        return {
            flag_id
            for row in queryset.values_list(
                "targeting_flag_id",
                "internal_targeting_flag_id",
                "internal_response_sampling_flag_id",
            )
            for flag_id in row
            if flag_id is not None
        }

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Surveys"),
            type="survey",  # sync with APIScopeObject in scopes.py
            ref=str(self.pk),
            name=self.name or "Untitled",
            href=f"/surveys/{self.pk}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=False,
        )


def update_response_sampling_limits(sender, instance, **kwargs):
    if (
        instance.response_sampling_interval_type is None
        or instance.response_sampling_limit == 0
        or instance.response_sampling_start_date is None
    ):
        instance.response_sampling_daily_limits = None
        return

    # Calculate the total number of days in the interval
    if instance.response_sampling_interval_type == "day":
        total_days = instance.response_sampling_interval
    elif instance.response_sampling_interval_type == "week":
        total_days = instance.response_sampling_interval * 7
    elif instance.response_sampling_interval_type == "month":
        total_days = instance.response_sampling_interval * 30  # Using average month length

    # Calculate responses per day
    responses_per_day = instance.response_sampling_limit // total_days
    remaining_responses = instance.response_sampling_limit % total_days

    # Calculate the daily rollout percentage increment
    rollout_increment = 100 / total_days

    # Generate the cumulative schedule
    schedule = []
    current_date = instance.response_sampling_start_date
    rollout_percentage = rollout_increment  # Start at 100 / total_days
    daily_response_limit = 0
    for day in range(total_days):
        daily_response_limit += responses_per_day + (1 if day < remaining_responses else 0)
        schedule.append(
            {
                "date": current_date.isoformat(),
                "daily_response_limit": daily_response_limit,
                "rollout_percentage": round(rollout_percentage, 2),  # Round to 2 decimal places
            }
        )
        current_date += timedelta(days=1)
        rollout_percentage += rollout_increment

    # Ensure the last day's rollout_percentage is exactly 100%
    schedule[-1]["rollout_percentage"] = 100.0

    # Save the schedule in the instance (convert to JSON or store as needed)
    instance.response_sampling_daily_limits = json.dumps(schedule)


@receiver(pre_save, sender=Survey)
def pre_save_survey(sender, instance, *args, **kwargs):
    update_survey_iterations(sender, instance)
    update_response_sampling_limits(sender, instance)
    ensure_question_ids(instance)


def ensure_question_ids(instance):
    """
    Ensures that each question in the survey has a unique ID.
    If a question doesn't have an ID, a new UUID is generated and assigned.
    """
    if not instance.questions:
        return

    for question in instance.questions:
        if not question.get("id"):
            question["id"] = str(uuid.uuid4())


def update_survey_iterations(sender, instance, *args, **kwargs):
    iteration_count = 0 if instance.iteration_count is None else instance.iteration_count
    iteration_frequency_dates = 0 if instance.iteration_frequency_days is None else instance.iteration_frequency_days

    if (
        instance.iteration_count is None
        or instance.iteration_frequency_days is None
        or instance.iteration_count == 0
        or instance.iteration_frequency_days == 0
    ):
        instance.iteration_start_dates = []
        instance.current_iteration = None
        instance.current_iteration_start_date = None
        return

    if instance.start_date is None:
        instance.iteration_start_dates = None
        return

    instance.iteration_start_dates = list(
        rrule(
            DAILY,
            count=min(iteration_count, MAX_ITERATION_COUNT),
            interval=iteration_frequency_dates,
            dtstart=instance.start_date,
        )
    )

    if iteration_count > 0 and (instance.current_iteration is None or instance.current_iteration == 0):
        instance.current_iteration = 1
        instance.current_iteration_start_date = instance.start_date


def _get_surveys_response(team: "Team") -> dict:
    from posthog.api.survey import get_surveys_response

    return get_surveys_response(team)


surveys_hypercache = HyperCache(
    namespace="surveys",
    value="surveys.json",
    load_fn=lambda key: _get_surveys_response(HyperCache.team_from_key(key)),
    token_based=True,
)


@receiver(post_save, sender=Survey)
@receiver(post_delete, sender=Survey)
def survey_changed(sender, instance: "Survey", **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache
    from posthog.tasks.surveys import update_team_surveys_cache

    # Defer task execution until after the transaction commits
    # Update both survey cache and flag cache since survey-linked flags are
    # excluded from local evaluation (GitHub issue #43631)
    transaction.on_commit(lambda: update_team_surveys_cache.delay(instance.team_id))
    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))
