from django.conf import settings


def ai_events_retention_days(team_id: int) -> int:
    """How long a row the team writes to `ai_events` today is kept.

    Rows written before the team's retention was extended keep the retention they were written with, so a read
    this far back can find nothing where older rows already expired.
    """
    return settings.AI_EVENTS_RETENTION_DAYS_BY_TEAM.get(team_id, settings.AI_EVENTS_DEFAULT_RETENTION_DAYS)
