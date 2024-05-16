from django.db.models import Q
from django.db.models import F
from datetime import date

from posthog.models import Survey


def _update_survey_iteration(survey):
    survey.refresh_from_db()
    if survey.iteration_start_dates is None or survey.end_date is not None:
        return

    survey.current_iteration = _get_current_iteration(survey)
    survey.current_iteration_start_date = survey.iteration_start_dates[survey.current_iteration - 1]
    survey.save(update_fields=["current_iteration", "current_iteration_start_date"])


def _get_current_iteration(survey):
    today_date = date.today()
    for idx, start_date in enumerate(survey.iteration_start_dates):
        delta = (today_date - start_date.date()).days
        if delta > 0 and delta < survey.iteration_frequency_days:
            return idx + 1

    return 0


def update_survey_iteration() -> None:
    surveys_with_recurring_schedules = (
        Survey.objects.exclude(Q(responses_limit__isnull=True) | Q(end_date__isnull=False))
        .exclude(Q(iteration_count=0), Q(iteration_count=F("current_iteration")))
        .only("id", "iteration_count", "iteration_start_dates")
    )

    for survey in list(surveys_with_recurring_schedules):
        _update_survey_iteration(survey)
