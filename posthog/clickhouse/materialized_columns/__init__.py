from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.clickhouse.materialized_columns.columns import *
else:
    from .column import *
