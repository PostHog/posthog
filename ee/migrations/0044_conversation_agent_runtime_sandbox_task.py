from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds Conversation.agent_runtime and Conversation.sandbox_task_fk.

    Strictly additive — the legacy `sandbox_task_id` and `sandbox_run_id` UUID columns
    from the Redis-relay flow stay in place. `sandbox_task_fk` is a real FK to the
    cloud-agent Task model that coexists with the legacy UUID during the migration;
    the spec name `sandbox_task` is reserved until the legacy column can be removed
    (its FK auto-attname `sandbox_task_id` collides with the existing UUID field
    today).

    See docs/internal/posthog-ai-migration/02_CORE.md § 2.
    """

    dependencies = [
        ("ee", "0043_teamsessionsummariesconfig_custom_tags"),
        ("tasks", "0031_task_github_user_integration"),
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
        migrations.AddField(
            model_name="conversation",
            name="sandbox_task_fk",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Foreign key to the cloud-agent Task backing this conversation when "
                    "agent_runtime is 'sandbox'. Coexists with the legacy `sandbox_task_id` "
                    "UUID column during the migration to a real FK (the spec name "
                    "`sandbox_task` is reserved until that column is removed — adding it "
                    "now would collide on the FK's auto-generated `sandbox_task_id` "
                    "attname). One Task per conversation; current Run is derived from "
                    "the Task's latest TaskRun."
                ),
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="+",
                to="tasks.task",
            ),
        ),
    ]
