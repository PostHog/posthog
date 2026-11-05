from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.team.team_event_volume import events_last_year_for
from posthog.ph_client import feature_enabled_or_false

TEAM_FIRST_PREWHERE_FLAG = "hogql-team-first-prewhere"
TEAM_FIRST_PREWHERE_MAX_EVENTS_LAST_YEAR = 100_000_000


def should_check_team_first_in_prewhere(team: Team) -> bool:
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
        events_last_year = events_last_year_for(team.pk)
    except Exception as e:
        capture_exception(e)
        return False
    return events_last_year is not None and events_last_year < TEAM_FIRST_PREWHERE_MAX_EVENTS_LAST_YEAR
