from django.conf import settings

from posthog.models.instance_setting import get_instance_setting


def use_new_events_schema(team_id: int | None = None) -> bool:
    """Whether HogQL reads should target the native-JSON events tables.

    The CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA env var pins the mode for CI and dev processes; in
    production the instance setting of the same name flips it globally at runtime, and the
    *_TEAMS instance setting enables it for individual teams first (both cached for up to 60s per
    worker). Code running inside a query should prefer HogQLContext.uses_new_events_schema(), which
    resolves this once so a mid-query flip can't mix schemas.
    """
    if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        return True
    if get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA"):
        return True
    return team_id is not None and team_id in _allowlisted_team_ids()


def _allowlisted_team_ids() -> set[int]:
    raw = str(get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS") or "")
    # Tolerate stray whitespace and non-numeric tokens — a typo in the setting must not break queries.
    return {int(part) for part in (piece.strip() for piece in raw.split(",")) if part.isdigit()}
