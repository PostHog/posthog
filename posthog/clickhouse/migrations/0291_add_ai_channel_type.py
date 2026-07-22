from infi.clickhouse_orm import migrations

from posthog.models.channel_type.sql import update_and_add_channel_types

# Adds the "AI" channel type sources (chatgpt, claude, gemini, copilot, grok, deepseek, and other AI
# assistants) and reclassifies the existing perplexity/phind/you.com/andisearch/komo.ai rows from Search
# to AI. Uses update_and_add_channel_types rather than add_missing_channel_types because those existing
# rows change type, which add_missing can't do — it only inserts new keys.
operations = [
    migrations.RunPython(update_and_add_channel_types),
]
