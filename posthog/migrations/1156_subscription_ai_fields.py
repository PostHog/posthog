# Generated manually

from django.db import migrations, models


def backfill_content_type(apps, schema_editor):
    Subscription = apps.get_model("posthog", "Subscription")
    Subscription.objects.filter(dashboard_id__isnull=False).update(content_type="dashboard")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1155_sharingconfiguration_interviewee_context"),
    ]

    operations = [
        # The index on `content_type` is added separately in
        # `1157_subscription_content_type_idx` via `AddIndexConcurrently` so the
        # production rollout doesn't take an ACCESS EXCLUSIVE lock building it.
        migrations.AddField(
            model_name="subscription",
            name="content_type",
            field=models.CharField(
                choices=[
                    ("insight", "Insight"),
                    ("dashboard", "Dashboard"),
                    ("ai_prompt", "Ai Prompt"),
                ],
                default="insight",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="prompt",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="subscription",
            name="ai_config",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.RunPython(backfill_content_type, reverse_code=noop_reverse),
    ]
