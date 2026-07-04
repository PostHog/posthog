from django.conf import settings

from posthog.models.instance_setting import get_instance_setting


def use_new_events_schema() -> bool:
    """Whether HogQL reads should target the native-JSON events tables.

    The CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA env var pins the mode for CI and dev processes; in
    production the instance setting of the same name flips it at runtime (cached for up to 60s per
    worker). Code running inside a query should prefer HogQLContext.uses_new_events_schema(), which
    resolves this once so a mid-query flip can't mix schemas.
    """
    if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        return True
    return bool(get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA"))
