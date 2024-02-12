from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.clickhouse.queries.retention.retention import (
        ClickhouseRetention as Retention,
    )
else:
    from posthog.queries.retention.retention import Retention  # type: ignore

from .retention import build_returning_event_query, build_target_event_query
