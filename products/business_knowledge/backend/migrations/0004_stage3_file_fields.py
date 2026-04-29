from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Stage 3: file-source metadata on KnowledgeSource.

    Additive — text and URL sources leave these columns at their defaults.
    """

    atomic = True

    dependencies = [
        ("business_knowledge", "0003_stage2b_crawl_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgesource",
            name="original_filename",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="file_content_type",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="file_size_bytes",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
