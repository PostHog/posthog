from django.db.models import Q
from django.db.models import F
from datetime import date
from posthog.models import Survey, FeatureFlag


def _update_survey_iteration(survey: Survey) -> None:
    survey.refresh_from_db()
    if survey.iteration_start_dates is None or survey.end_date is not None:
        return

    survey.current_iteration = _get_current_iteration(survey)
    survey.current_iteration_start_date = survey.iteration_start_dates[survey.current_iteration - 1]
    survey.save(update_fields=["current_iteration", "current_iteration_start_date"])
    _update_internal_targeting_flag(survey)


def _update_internal_targeting_flag(survey: Survey) -> None:
    survey.refresh_from_db()
    if survey.iteration_start_dates is None or survey.end_date is not None:
        return

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

    existing_targeting_flag = survey.internal_targeting_flag
    if existing_targeting_flag:
        existing_targeting_flag = survey.internal_targeting_flag
        serialized_data_filters = {**user_submitted_dismissed_filter, **existing_targeting_flag.filters}
        existing_targeting_flag.filters = serialized_data_filters
        existing_targeting_flag.save()
    else:
        survey.internal_targeting_flag = FeatureFlag.objects.create(
            team=survey.team,
            created_by=survey.created_by,
            active=True,
            key=survey.id,
            filters=user_submitted_dismissed_filter,
        )
        survey.save()


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
    surveys_with_recurring_schedules = (
        Survey.objects.exclude(Q(end_date__isnull=False))
        .exclude(Q(iteration_count=0), Q(iteration_count=F("current_iteration")))
        .only("id", "iteration_count", "iteration_start_dates")
    )

    for survey in list(surveys_with_recurring_schedules):
        _update_survey_iteration(survey)
