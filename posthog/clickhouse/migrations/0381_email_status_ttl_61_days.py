from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.messaging.backend.facade.clickhouse import EMAIL_STATUS_DATA_TTL_SQL

operations = (
    [
        run_sql_with_exceptions(
            EMAIL_STATUS_DATA_TTL_SQL(),
            node_roles=[NodeRole.AUX],
            sharded=False,
            is_alter_on_replicated_table=True,
        ),
    ]
    if not settings.TEST
    else []
)
