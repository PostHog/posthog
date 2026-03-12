# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1046_migrate_evaluation_tags_to_contexts"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="quick_filter_ids",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
