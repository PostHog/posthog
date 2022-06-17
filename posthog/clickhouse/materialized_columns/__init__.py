from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.analyze import *
    from ee.clickhouse.materialized_columns.columns import *
else:
    from .analyze import *  # type: ignore
    from .column import *
