from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0954_experiment_scheduling_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="failure_type",
            field=models.CharField(blank=True, max_length=256, null=True),
        ),
    ]
