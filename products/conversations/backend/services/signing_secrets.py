from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity


def log_signing_secret_change(team: Team, changes: list[Change], *, user: User | None, was_impersonated: bool) -> None:
    """Audit write shared by every signing secret change (rotate, expire, leak
    retirement), so all entries carry the same scope and fields."""
    log_activity(
        organization_id=team.organization_id,
        team_id=team.id,
        user=user,
        was_impersonated=was_impersonated,
        scope="Team",
        item_id=team.id,
        activity="updated",
        detail=Detail(name=str(team.name), changes=changes),
    )
