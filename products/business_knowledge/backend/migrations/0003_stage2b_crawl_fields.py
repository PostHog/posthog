from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Stage 2b: introduce crawl mode fields on KnowledgeSource.

    Additive — existing Stage 2a rows default to crawl_mode="single" so the
    refresh path stays byte-for-byte compatible.
    """

    atomic = True

    dependencies = [
        ("business_knowledge", "0002_stage2a_url_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgesource",
            name="crawl_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("single", "Single page"),
                    ("sitemap", "Sitemap"),
                    ("same_origin", "Same origin crawl"),
                    ("github_repo", "GitHub repository"),
                ],
                default="single",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="knowledgesource",
            name="crawl_config",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
