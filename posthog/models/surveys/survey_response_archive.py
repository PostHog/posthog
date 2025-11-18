from django.db import models


class SurveyResponseArchive(models.Model):
    """
    Separate table to track archived survey responses, since survey results are
    stored as ClickHouse events
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="survey_response_archives",
        related_query_name="survey_response_archive",
    )
    survey = models.ForeignKey(
        "posthog.Survey",
        on_delete=models.CASCADE,
        related_name="response_archives",
        related_query_name="response_archive",
    )
    response_uuid = models.UUIDField(help_text="UUID of the ClickHouse event representing the survey response")
    archived_at = models.DateTimeField(auto_now_add=True)
    archived_by = models.ForeignKey(
        "posthog.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archived_survey_responses",
        related_query_name="archived_survey_response",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "response_uuid"],
                name="unique_archived_response_per_team",
            )
        ]
        indexes = [
            models.Index(fields=["survey", "team"]),
            models.Index(fields=["team", "response_uuid"]),
        ]

    def __str__(self):
        return f"Archived response {self.response_uuid} for survey {self.survey_id}"
