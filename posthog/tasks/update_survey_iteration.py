from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.tasks.survey_system_stop import log_survey_stopped_by_system

from products.feature_flags.backend.facade.api import create_flag, update_flag
from products.feature_flags.backend.facade.filters import replace_release_conditions
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.surveys.backend.models import Survey, open_ended_iteration, update_survey_iterations


def _update_survey_iteration(survey: Survey) -> None:
    survey.refresh_from_db()
    if survey.iteration_start_dates is None or survey.end_date is not None:
        return

    # An open-ended schedule keeps only the windows up to the next one, so extend them before reading.
    update_survey_iterations(Survey, survey)

    final_iteration_end = _get_final_iteration_end(survey)
    if final_iteration_end is not None and date.today() > final_iteration_end:
        if not _was_resumed_by_a_person_after(survey, final_iteration_end):
            survey.end_date = timezone.now()
            survey.save(update_fields=["end_date"])
            _log_survey_closed_by_schedule(survey)
        return

    current_iteration = _get_current_iteration(survey)
    if (
        current_iteration > 0
        and current_iteration != survey.current_iteration
        and survey.iteration_start_dates is not None
        and 0 < len(survey.iteration_start_dates)
    ):
        survey.current_iteration = current_iteration
        # Open-ended surveys store only the current and the next window.
        window_index = 0 if survey.repeat_until_stopped else survey.current_iteration - 1
        survey.current_iteration_start_date = survey.iteration_start_dates[window_index]
        survey.internal_targeting_flag = _get_targeting_flag(survey)
        survey.save(
            update_fields=[
                "current_iteration",
                "current_iteration_start_date",
                "internal_targeting_flag_id",
                "iteration_start_dates",
            ]
        )


def _log_survey_closed_by_schedule(survey: Survey) -> None:
    # Record a system activity-log entry so the survey's history explains why it stopped.
    # Without this, the scheduler's direct save() leaves no trace, and a user who removes
    # the end date only ever sees their own removals logged — never the automatic close.
    log_survey_stopped_by_system(
        survey,
        "survey_schedule_ended",
        {"iteration_count": survey.iteration_count, "iteration_frequency_days": survey.iteration_frequency_days},
    )


def _get_final_iteration_end(survey: Survey) -> date | None:
    if survey.repeat_until_stopped or not survey.iteration_start_dates or not survey.iteration_frequency_days:
        return None

    last_iteration_start = survey.iteration_start_dates[-1]
    if last_iteration_start is None:
        return None

    try:
        return last_iteration_start.date() + timedelta(days=survey.iteration_frequency_days)
    except OverflowError:
        # iteration_frequency_days is not capped by the API; a huge value must not crash the task
        return None


def _was_resumed_by_a_person_after(survey: Survey, day: date) -> bool:
    # The iteration dates stay anchored to start_date, so a survey resumed after its schedule ended
    # still looks finished. Closing it again would silently undo the person's resume.
    return ActivityLog.objects.filter(
        team_id=survey.team_id,
        scope="Survey",
        item_id=str(survey.id),
        is_system=False,
        created_at__date__gt=day,
        detail__changes__contains=[{"field": "end_date", "after": None}],
    ).exists()


def _get_targeting_flag(survey: Survey) -> FeatureFlag:
    existing_targeting_flag: FeatureFlag | None = survey.internal_targeting_flag
    user_submitted_dismissed_groups = [
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

    if existing_targeting_flag is not None:
        # Note: groups are replaced wholesale so old iteration-unaware properties don't survive
        return update_flag(
            existing_targeting_flag,
            {
                "filters": replace_release_conditions(
                    existing_targeting_flag.get_filters(), user_submitted_dismissed_groups
                )
            },
            team=survey.team,
            # system write: skips the approval gate, same as the create_flag call below
            user=None,
        )
    # user=None: this is beat-task maintenance, so it must take the system-write
    # path — a user-bearing write would engage the approval gate, and this task
    # cannot surface an ApprovalRequired change request.
    flag = create_flag(
        {
            "key": str(survey.id),
            "active": True,
            "filters": {"groups": user_submitted_dismissed_groups},
            "creation_context": "surveys",
        },
        team=survey.team,
        user=None,
    )
    # The system write nulls created_by, which would cost the survey's creator their
    # guaranteed access to the flag. Restore attribution with a raw column update:
    # QuerySet.update() bypasses save()/signals, so the write stays system-attributed
    # (is_system activity log, null last_modified_by) and cannot engage the gate.
    if survey.created_by is not None:
        FeatureFlag.objects.filter(pk=flag.pk).update(created_by=survey.created_by)
        flag.created_by = survey.created_by
    return flag


def _get_current_iteration(survey: Survey) -> int:
    if survey.iteration_start_dates is None or not survey.iteration_frequency_days or survey.end_date is not None:
        return 0

    if survey.repeat_until_stopped and survey.start_date is not None:
        return open_ended_iteration(survey.start_date, survey.iteration_frequency_days, timezone.now())

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
    # `schedule` is the user's intent. The iteration_* columns can outlive it on rows that predate
    # the field or were written by an API client, so they alone do not make a survey recurring.
    surveys_with_recurring_schedules = Survey.objects.filter(
        Q(iteration_count__isnull=False) | Q(repeat_until_stopped=True),
        start_date__isnull=False,
        end_date__isnull=True,
        schedule=Survey.Schedule.RECURRING,
    ).only(
        "id",
        "schedule",
        "start_date",
        "end_date",
        "iteration_count",
        "iteration_frequency_days",
        "repeat_until_stopped",
        "iteration_start_dates",
        "current_iteration",
    )

    for survey in list(surveys_with_recurring_schedules):
        _update_survey_iteration(survey)
