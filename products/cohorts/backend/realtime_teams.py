from django.conf import settings


def is_realtime_cohort_team(team_id: int) -> bool:
    """Mirror the Rust `REALTIME_COHORT_TEAM_ALLOWLIST` gate by convention."""
    raw_allowlist = settings.REALTIME_COHORT_TEAM_ALLOWLIST.strip()
    if raw_allowlist.lower() == "all":
        return True

    try:
        allowed_team_ids = {int(value.strip()) for value in raw_allowlist.split(",") if value.strip()}
    except ValueError:
        return False
    return team_id in allowed_team_ids
