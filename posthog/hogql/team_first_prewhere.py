from datetime import timedelta

from django.utils.timezone import now

from posthog.cache_utils import cache_for
from posthog.clickhouse.workload import Workload
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.team.team_event_volume import TeamEventVolume
from posthog.ph_client import feature_enabled_or_false

TEAM_FIRST_PREWHERE_FLAG = "hogql-team-first-prewhere"
TEAM_FIRST_PREWHERE_MAX_EVENTS_LAST_YEAR = 100_000_000
TEAM_EVENT_VOLUME_MAX_AGE = timedelta(days=3)


@cache_for(timedelta(minutes=10))
def _recent_events_last_year(team_id: int) -> int | None:
    return (
        TeamEventVolume.objects.for_team(team_id)
        .filter(computed_at__gte=now() - TEAM_EVENT_VOLUME_MAX_AGE)
        .values_list("events_last_year", flat=True)
        .first()
    )


def should_check_team_first_in_prewhere(team: Team, workload: Workload | None) -> bool:
    if workload == Workload.LOGS:
        return False
    try:
        if not feature_enabled_or_false(
            TEAM_FIRST_PREWHERE_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.pk)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.pk)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        ):
            return False
        events_last_year = _recent_events_last_year(team.pk)
    except Exception as e:
        capture_exception(e)
        return False
    return events_last_year is not None and events_last_year < TEAM_FIRST_PREWHERE_MAX_EVENTS_LAST_YEAR
