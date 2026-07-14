from infi.clickhouse_orm import migrations

from posthog.models.channel_type.sql import rebuild_channel_definitions

# Adds the "AI" channel type sources (chatgpt, claude, gemini, copilot, grok, deepseek) and
# reclassifies the perplexity sources from Search to AI. A full rebuild rather than
# add_missing_channel_types because existing rows change type, not just get added.
operations = [
    migrations.RunPython(rebuild_channel_definitions),
]
