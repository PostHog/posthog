from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.person_group_membership.sql import (
    GROUP_KEY_EXPR,
    KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE,
    PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY,
    PERSON_GROUP_MEMBERSHIP_MV,
)

# The SELECT is a copy of the one sql.py held for this migration, not an import.
# A node with this migration pending has the Kafka table of that time.
# A column that a later migration adds to the sql.py SELECT does not exist there yet.
DICTIONARY = f"{settings.CLICKHOUSE_DATABASE}.{PERSON_GROUP_MEMBERSHIP_CONFIG_DICTIONARY}"

operations = [
    run_sql_with_exceptions(
        f"""ALTER TABLE {settings.CLICKHOUSE_DATABASE}.{PERSON_GROUP_MEMBERSHIP_MV} MODIFY QUERY SELECT
    team_id,
    group_type_index,
    {GROUP_KEY_EXPR} AS group_key,
    distinct_id,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM (
    SELECT
        team_id,
        dictGet('{DICTIONARY}', 'group_type_index', tuple(team_id)) AS group_type_index,
        distinct_id,
        properties,
        timestamp
    FROM {settings.CLICKHOUSE_DATABASE}.{KAFKA_PERSON_GROUP_MEMBERSHIP_TABLE}
    WHERE dictHas('{DICTIONARY}', tuple(team_id)) AND (person_mode != 'propertyless')
      AND JSONExtractRaw(properties, '$update_person_last_seen_at') != 'false'
)
WHERE notEmpty(group_key)
GROUP BY team_id, group_type_index, group_key, distinct_id""",
        node_roles=[NodeRole.INGESTION_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
        require_hosts=True,
    ),
]
