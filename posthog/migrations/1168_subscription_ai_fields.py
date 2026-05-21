# Generated manually

from django.db import migrations, models


def backfill_content_type(apps, schema_editor):
    Subscription = apps.get_model("posthog", "Subscription")
    Subscription.objects.filter(dashboard_id__isnull=False).update(content_type="dashboard")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1167_remove_alertconfiguration_is_calculating"),
    ]

    operations = [
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
