from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.channel_type.sql import (
    CHANNEL_DEFINITION_DATA_SQL,
    CHANNEL_DEFINITION_DICTIONARY_NAME,
    CHANNEL_DEFINITION_TABLE_NAME,
)

# Refreshes channel_definition with the AI channel type sources (chatgpt, claude, gemini, etc.), including
# the perplexity/phind/you.com/andisearch/komo.ai rows reclassified from Search to AI. Nothing reads the
# table at query time (all reads go through channel_definition_dict), so truncate + full reinsert is safe:
# the dictionary serves its cached snapshot until the explicit reload. Writes run on one host
# (is_alter_on_replicated_table) and replication fans out.
operations = [
    run_sql_with_exceptions(
        f"TRUNCATE TABLE IF EXISTS {CHANNEL_DEFINITION_TABLE_NAME}",
        node_roles=[NodeRole.DATA],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        CHANNEL_DEFINITION_DATA_SQL(),
        node_roles=[NodeRole.DATA],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"SYSTEM RELOAD DICTIONARY {CHANNEL_DEFINITION_DICTIONARY_NAME}",
        node_roles=[NodeRole.DATA],
    ),
]

# The sessions satellite serves channel classification for session queries via its own per-node dictionary,
# but its channel_definition differs per region (see posthog/clickhouse/hcl/roles/sessions/): US keeps an
# independent replica set (own zookeeper path) that the main-cluster write never reaches, so it needs its
# own truncate + reinsert; EU only has a Distributed wrapper over the main-cluster table (never TRUNCATE
# that), so a dictionary reload suffices. Local/hobby/dev sessions nodes carry neither (prod-only tables).
if settings.CLOUD_DEPLOYMENT == "US":
    operations += [
        run_sql_with_exceptions(
            f"TRUNCATE TABLE IF EXISTS {CHANNEL_DEFINITION_TABLE_NAME}",
            node_roles=[NodeRole.SESSIONS],
            is_alter_on_replicated_table=True,
        ),
        run_sql_with_exceptions(
            CHANNEL_DEFINITION_DATA_SQL(),
            node_roles=[NodeRole.SESSIONS],
            is_alter_on_replicated_table=True,
        ),
    ]
if settings.CLOUD_DEPLOYMENT in ("US", "EU"):
    operations.append(
        run_sql_with_exceptions(
            f"SYSTEM RELOAD DICTIONARY {CHANNEL_DEFINITION_DICTIONARY_NAME}",
            node_roles=[NodeRole.SESSIONS],
        )
    )
