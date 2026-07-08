from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0014_knowledge_gap_suggestion"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="knowledgegapsuggestion",
            index=models.Index(
                fields=["team", "status", "normalized_topic"],
                name="bk_gap_team_status_topic",
            ),
        ),
    ]
