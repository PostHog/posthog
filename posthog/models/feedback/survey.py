from django.db import models
from posthog.models.utils import UUIDModel


class Survey(UUIDModel):
    class SurveyType(models.TextChoices):
        POPOVER = "popover", "popover"
        BUTTON = "button", "button"
        EMAIL = "email", "email"
        FULL_SCREEN = "full_screen", "full screen"
        API = "api", "api"

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "name"], name="unique survey name for team")]

    team: models.ForeignKey = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, related_name="surveys", related_query_name="survey"
    )
    name: models.CharField = models.CharField(max_length=400)
    description: models.TextField = models.TextField(blank=True)
    linked_flag: models.ForeignKey = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_linked_flag",
        related_query_name="survey",
    )
    targeting_flag: models.ForeignKey = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_targeting_flag",
        related_query_name="survey",
    )
    type: models.CharField = models.CharField(max_length=40, choices=SurveyType.choices)

    # { url: 'posthog.com/feature', selector: null, triggers: [{}] #similar to cohort behavioral filters for now?}
    conditions: models.JSONField = models.JSONField(blank=True, null=True)

    # class SurveyQuestionType(models.TextChoices):
    #     OPEN = "open"
    #     MULTIPLE_CHOICE_SINGLE = "multiple"
    #     NPS = "nps"
    #     RATING = "rating"
    # [ { type: 'open', question: "leave feedback plz?"}, { type: 'rating', question: null}, { type: 'multiple_choice', question: "multiple choice question?", choices: ["choice 1", "choice 2"]} ]
    questions: models.JSONField = models.JSONField(blank=True, null=True)

    # { background_color: "white", button_color: "orange", text_color: "", position, etc... }
    appearance: models.JSONField = models.JSONField(blank=True, null=True)

    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    created_by: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="surveys",
        related_query_name="survey",
        null=True,
    )
    start_date: models.DateTimeField = models.DateTimeField(null=True)
    end_date: models.DateTimeField = models.DateTimeField(null=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    archived: models.BooleanField = models.BooleanField(default=False)
