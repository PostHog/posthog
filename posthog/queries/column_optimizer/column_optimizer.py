# isort: skip_file
from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.clickhouse.queries.column_optimizer import (
        EnterpriseColumnOptimizer as ColumnOptimizer,
    )
else:
    from posthog.queries.column_optimizer.foss_column_optimizer import (  # type: ignore
        FOSSColumnOptimizer as ColumnOptimizer,  # noqa: F401
    )
