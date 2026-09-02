from django.conf import settings

# Matches the Rust range-span cap in rust/common/types/src/cohort.rs.
_MAX_RANGE_SPAN = 100_000


def _matches_every_team(raw_allowlist: str) -> bool:
    raw_allowlist = raw_allowlist.strip()
    return raw_allowlist == "" or raw_allowlist.lower() == "all" or raw_allowlist == "*"


def _team_in_allowlist(raw_allowlist: str, team_id: int) -> bool:
    """Whether ``team_id`` matches a team-allowlist setting.

    Mirrors the Rust ``TeamAllowlist`` grammar (``rust/common/types/src/cohort.rs``) that parses
    ``REALTIME_COHORT_TEAM_ALLOWLIST`` — keep the two in sync so Django's edit-time readiness
    invalidation covers exactly the teams Rust maintains realtime membership for.

    Grammar: empty / ``all`` / ``*`` match every team; ``none`` matches none; otherwise a comma list
    of signed integer ids and inclusive ``start:end`` ranges (each capped at ``_MAX_RANGE_SPAN``).
    Malformed tokens are ignored — the Rust side rejects the whole value at startup.
    """
    raw_allowlist = raw_allowlist.strip()
    if _matches_every_team(raw_allowlist):
        return True
    if raw_allowlist.lower() == "none":
        return False

    for part in (segment.strip() for segment in raw_allowlist.split(",")):
        if not part:
            continue
        start_raw, is_range, end_raw = part.partition(":")
        try:
            if is_range:
                start, end = int(start_raw.strip()), int(end_raw.strip())
            else:
                start = end = int(part)
        except ValueError:
            continue
        if start <= end <= start + _MAX_RANGE_SPAN - 1 and start <= team_id <= end:
            return True
    return False


def realtime_allowlist_matches_every_team() -> bool:
    """Whether the realtime allowlist is one of the match-everything values.

    Lets a caller skip enumerating every team to rediscover that the allowlist covers all of them.
    """
    return _matches_every_team(settings.REALTIME_COHORT_TEAM_ALLOWLIST)


def is_realtime_cohort_team(team_id: int) -> bool:
    """Whether the realtime-cohort pipeline is scoped to ``team_id``."""
    return _team_in_allowlist(settings.REALTIME_COHORT_TEAM_ALLOWLIST, team_id)


def is_cohort_backfill_trigger_team(team_id: int) -> bool:
    """Whether saving a cohort in ``team_id`` should enqueue backfill runs for it."""
    if not settings.COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST.strip():
        # No Rust service parses this setting, so it can fail closed on empty where the realtime
        # allowlist cannot: a set-but-empty value means no teams, not every team.
        return False
    return _team_in_allowlist(settings.COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST, team_id)
