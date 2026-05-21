from django.db import migrations, models


class Migration(migrations.Migration):
    """Conversation model migration for the PostHog AI sandbox runtime.

    Adds `agent_runtime` (stamped at create-time from the posthog-ai-sandbox flag) and a
    real FK `sandbox_task` to the cloud-agent Task model. Drops the legacy `sandbox_task_id`
    and `sandbox_run_id` UUID columns from the unshipped Redis-relay flow — no data to
    preserve, so a clean replacement is preferred over an in-place rename via
    `SeparateDatabaseAndState`. Current Run is derived from the Task's latest TaskRun, so
    no `sandbox_run_id` replacement is needed.

    See docs/internal/posthog-ai-migration/02_CORE.md § 2 for the rationale.
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
        migrations.RemoveField(
            model_name="conversation",
            name="sandbox_task_id",
        ),
        migrations.RemoveField(
            model_name="conversation",
            name="sandbox_run_id",
        ),
        migrations.AddField(
            model_name="conversation",
            name="sandbox_task",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Cloud-agent Task backing this conversation when agent_runtime is "
                    "'sandbox'. One Task per conversation; current Run is derived from "
                    "the Task's latest TaskRun."
                ),
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="+",
                to="tasks.task",
            ),
        ),
    ]
