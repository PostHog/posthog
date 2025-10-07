from django.conf import settings

from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.kafka_client.topics import KAFKA_EVENTS_JSON
from posthog.models.kafka_debug.sql import KafkaDebugKafkaTable, KafkaDebugMaterializedView, KafkaDebugTable
<<<<<<< Updated upstream
=======
from django.conf import settings
>>>>>>> Stashed changes

debug_table = KafkaDebugTable(topic=KAFKA_EVENTS_JSON)
kafka_table = KafkaDebugKafkaTable(brokers=settings.KAFKA_HOSTS, topic=KAFKA_EVENTS_JSON)
materialized_view = KafkaDebugMaterializedView(to_table=debug_table, from_table=kafka_table)


operations = [
    run_sql_with_exceptions(kafka_table.get_drop_table_sql()),
    run_sql_with_exceptions(materialized_view.get_drop_view_sql()),
    run_sql_with_exceptions(debug_table.get_drop_table_sql()),
]
