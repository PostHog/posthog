from datetime import date, timedelta
from typing import Any

from django.utils import timezone

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.surveys.backend.models import Survey


def _update_survey_iteration(survey: Survey) -> None:
    survey.refresh_from_db()
    if survey.iteration_start_dates is None or survey.end_date is not None:
        return

    if _has_final_iteration_ended(survey):
        survey.end_date = timezone.now()
        survey.save(update_fields=["end_date"])
        return

    current_iteration = _get_current_iteration(survey)
    if (
        current_iteration > 0
        and current_iteration != survey.current_iteration
        and survey.iteration_start_dates is not None
        and 0 < len(survey.iteration_start_dates)
    ):
        survey.current_iteration = current_iteration
        survey.current_iteration_start_date = survey.iteration_start_dates[survey.current_iteration - 1]
        survey.internal_targeting_flag = _get_targeting_flag(survey)
        survey.save(update_fields=["current_iteration", "current_iteration_start_date", "internal_targeting_flag_id"])


def _has_final_iteration_ended(survey: Survey) -> bool:
    if not survey.iteration_start_dates or not survey.iteration_frequency_days:
        return False

    last_iteration_start = survey.iteration_start_dates[-1]
    if last_iteration_start is None:
        return False

    final_iteration_end = last_iteration_start.date() + timedelta(days=survey.iteration_frequency_days)
    return date.today() > final_iteration_end


def _get_targeting_flag(survey: Survey) -> FeatureFlag | Any:
    existing_targeting_flag: FeatureFlag | None = survey.internal_targeting_flag
    user_submitted_dismissed_filter = {
        "groups": [
            {
                "variant": "",
                "rollout_percentage": 100,
                "properties": [
                    {
                        "key": f"$survey_dismissed/{survey.id}/{survey.current_iteration}",
                        "value": "is_not_set",
                        "operator": "is_not_set",
                        "type": "person",
                    },
                    {
                        "key": f"$survey_responded/{survey.id}/{survey.current_iteration}",
                        "value": "is_not_set",
                        "operator": "is_not_set",
                        "type": "person",
                    },
                ],
            }
        ]
    }

    if existing_targeting_flag is not None:
        # Note: new filters must come LAST to overwrite old iteration-unaware properties
        serialized_data_filters = {**existing_targeting_flag.filters, **user_submitted_dismissed_filter}
        existing_targeting_flag.filters = serialized_data_filters
        existing_targeting_flag.save()
        return existing_targeting_flag
    else:
        new_flag = FeatureFlag.objects.create(
            team=survey.team,
            created_by=survey.created_by,
            active=True,
            key=str(survey.id),
            filters=user_submitted_dismissed_filter,
        )
        new_flag.save()
        return new_flag


def _get_current_iteration(survey: Survey) -> int:
    if survey.iteration_start_dates is None or survey.iteration_frequency_days is None or survey.end_date is not None:
        return 0

    today_date = date.today()
    idx = 0
    for start_date in survey.iteration_start_dates:
        if start_date is not None and survey.iteration_frequency_days is not None:
            idx += 1
            delta = (today_date - start_date.date()).days
            if 0 <= delta <= survey.iteration_frequency_days:
                return idx

    return 0


def update_survey_iteration() -> None:
    surveys_with_recurring_schedules = Survey.objects.filter(
        start_date__isnull=False, end_date__isnull=True, iteration_count__isnull=False
    ).only("id", "iteration_count", "iteration_start_dates")

    for survey in list(surveys_with_recurring_schedules):
        _update_survey_iteration(survey)
