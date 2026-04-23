from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Stage 2a: introduce URL-source schema.

    Purely additive, all new columns are nullable or have safe defaults so
    this can roll forward and back without touching existing Stage 1 rows.
    """

    atomic = True

    dependencies = [
        ("business_knowledge", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgesource",
            name="source_url",
            field=models.URLField(blank=True, default="", max_length=2048),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="last_refresh_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="last_refresh_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("success", "Success"),
                    ("not_modified", "Not modified"),
                    ("error", "Error"),
                ],
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="last_refresh_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="last_etag",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="knowledgedocument",
            name="url",
            field=models.URLField(blank=True, default="", max_length=2048),
        ),
        migrations.AddField(
            model_name="knowledgedocument",
            name="etag",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="knowledgedocument",
            name="content_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="knowledgedocument",
            name="tombstoned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
