from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds Conversation.agent_runtime for the PostHog AI sandbox runtime.

    Strictly additive — the legacy `sandbox_task_id` and `sandbox_run_id` UUID columns
    from the Redis-relay flow stay in place. The current Run is derived from those
    fields via the `current_sandbox_run` property on the model rather than a stored
    pointer; see docs/internal/posthog-ai-migration/02_CORE.md § 2.
    """

    dependencies = [
        ("ee", "0043_teamsessionsummariesconfig_custom_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="agent_runtime",
            field=models.CharField(
                choices=[("langgraph", "LangGraph"), ("sandbox", "Sandbox")],
                db_index=True,
                default="langgraph",
                help_text=(
                    "Which agent runtime backs this conversation. Stamped at create time "
                    "from the posthog-ai-sandbox flag; never re-read on an existing row."
                ),
                max_length=16,
            ),
        ),
    ]
