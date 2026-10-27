from posthog.event_usage import groups, report_user_action
from posthog.models import Team, User
from posthog.ph_client import ph_scoped_capture


def track(team: Team, user: User, event: str, properties: dict) -> None:
    report_user_action(user, event, properties, team=team)


def track_from_task(team: Team, user: User, event: str, properties: dict) -> None:
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=user.distinct_id,
            event=event,
            properties=properties,
            groups=groups(team.organization, team),
        )
