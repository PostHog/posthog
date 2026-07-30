from django.conf import settings

# Matches the Rust range-span cap in rust/common/types/src/cohort.rs.
_MAX_RANGE_SPAN = 100_000


def is_realtime_cohort_team(team_id: int) -> bool:
    """Whether the realtime-cohort pipeline is scoped to ``team_id``.

    Mirrors the Rust ``TeamAllowlist`` grammar (``rust/common/types/src/cohort.rs``) that parses
    ``REALTIME_COHORT_TEAM_ALLOWLIST`` — keep the two in sync so Django's edit-time readiness
    invalidation covers exactly the teams Rust maintains realtime membership for.

    Grammar: empty / ``all`` / ``*`` match every team; ``none`` matches none; otherwise a comma list
    of signed integer ids and inclusive ``start:end`` ranges (each capped at ``_MAX_RANGE_SPAN``).
    Malformed tokens are ignored — the Rust side rejects the whole value at startup.
    """
    raw_allowlist = settings.REALTIME_COHORT_TEAM_ALLOWLIST.strip()
    if raw_allowlist == "" or raw_allowlist.lower() == "all" or raw_allowlist == "*":
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
