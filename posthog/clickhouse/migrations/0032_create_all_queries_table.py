from infi.clickhouse_orm import migrations

from posthog.settings import CLICKHOUSE_CLUSTER

operations = [
    migrations.RunSQL(
        f"CREATE TABLE cluster_query_log ON CLUSTER '{CLICKHOUSE_CLUSTER}' AS system.query_log Engine=Distributed({CLICKHOUSE_CLUSTER}, system, query_log);"
    ),
]
