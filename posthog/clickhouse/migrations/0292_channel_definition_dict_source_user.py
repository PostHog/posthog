from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.channel_type.sql import CHANNEL_DEFINITION_DICTIONARY_NAME, CHANNEL_DEFINITION_DICTIONARY_SQL

# Re-points channel_definition_dict's source read at the default user. On the main cluster
# `dict_reader` has no SELECT grant on channel_definition, so every LIFETIME reload of the
# dictionary is denied, and a dictionary in that state fails every dictGetOrNull against it —
# the $channel_type breakdown, the $initial_channel_type virtual field, generic HogQL, and the
# SYSTEM RELOAD DICTIONARY that channel-definition migrations end with.
#
# CREATE OR REPLACE swaps the definition atomically, so there is no window where the dictionary
# is missing. The reload afterwards pulls the source immediately instead of leaving the
# dictionary failed until its next reload window (LIFETIME is up to an hour).
#
# DATA only: the sessions satellite carries its own channel_definition_dict, and its source reads
# are not being denied, so it keeps sourcing as dict_reader.
operations = [
    run_sql_with_exceptions(
        CHANNEL_DEFINITION_DICTIONARY_SQL(on_cluster=False, replace=True),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        f"SYSTEM RELOAD DICTIONARY {CHANNEL_DEFINITION_DICTIONARY_NAME}",
        node_roles=[NodeRole.DATA],
    ),
]
