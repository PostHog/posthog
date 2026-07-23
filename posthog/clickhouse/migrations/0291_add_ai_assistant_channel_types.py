from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.channel_type.sql import CHANNEL_DEFINITION_DATA_SQL

AI_ASSISTANT_CHANNEL_DEFINITIONS = [
    ("ai.perplexity.app", "source", "AI", None, "AI Assistant"),
    ("chatgpt.com", "source", "AI", None, "AI Assistant"),
    ("claude.ai", "source", "AI", None, "AI Assistant"),
    ("copilot.microsoft.com", "source", "AI", None, "AI Assistant"),
    ("gemini.google.com", "source", "AI", None, "AI Assistant"),
    ("meta.ai", "source", "AI", None, "AI Assistant"),
    ("perplexity.ai", "source", "AI", None, "AI Assistant"),
    ("pi.ai", "source", "AI", None, "AI Assistant"),
    ("poe.com", "source", "AI", None, "AI Assistant"),
    ("you.com", "source", "AI", None, "AI Assistant"),
]

operations = [
    # ai.perplexity.app, perplexity.ai and you.com already have rows from migration 0069
    # (classified under Organic Search). Remove them first so the dictionary's
    # (domain, kind) key stays unique before re-inserting with the new classification.
    run_sql_with_exceptions(
        "ALTER TABLE channel_definition DELETE WHERE kind = 'source' AND domain IN "
        "('ai.perplexity.app', 'chatgpt.com', 'claude.ai', 'copilot.microsoft.com', "
        "'gemini.google.com', 'meta.ai', 'perplexity.ai', 'pi.ai', 'poe.com', 'you.com') "
        "SETTINGS mutations_sync = 2",
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(CHANNEL_DEFINITION_DATA_SQL(channel_definitions=AI_ASSISTANT_CHANNEL_DEFINITIONS)),
]
