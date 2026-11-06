from typing import Any

from posthog.models.activity_logging.activity_log import Change, Detail, Trigger, log_activity

from products.surveys.backend.models import Survey


def log_survey_stopped_by_system(survey: Survey, job_type: str, payload: dict[str, Any]) -> None:
    log_activity(
        organization_id=survey.team.organization_id,
        team_id=survey.team_id,
        user=None,  # system action: renders as PostHog in the activity log
        was_impersonated=False,
        item_id=survey.id,
        scope="Survey",
        activity="updated",
        detail=Detail(
            name=survey.name,
            changes=[Change(type="Survey", field="end_date", action="created", after=survey.end_date)],
            trigger=Trigger(job_type=job_type, job_id=str(survey.id), payload=payload),
        ),
    )
