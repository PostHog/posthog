from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.messaging.backend.facade.clickhouse import EMAIL_STATUS_DATA_TTL_SQL

# Raises the email_status TTL from 31 to 61 days, so the status read can answer for a send up to 60 days old: a send
# that waited 30 days to go out stays readable for 30 days after it went out. email_status_events keeps its 31 days.
#
# Tables in tests have no TTL. See ttl_period().
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
