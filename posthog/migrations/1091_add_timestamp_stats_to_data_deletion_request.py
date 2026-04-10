from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1090_batchexportrun_records_failed"),
    ]

    operations = [
        migrations.AddField(
            model_name="datadeletionrequest",
            name="max_timestamp",
            field=models.DateTimeField(blank=True, help_text="Latest timestamp of matching events.", null=True),
        ),
        migrations.AddField(
            model_name="datadeletionrequest",
            name="min_timestamp",
            field=models.DateTimeField(
                blank=True,
                help_text="Earliest timestamp of matching events.",
                null=True,
            ),
        ),
    ]
