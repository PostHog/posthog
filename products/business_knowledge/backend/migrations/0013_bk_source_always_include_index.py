from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0012_knowledgesource_always_include"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="knowledgesource",
                    index=models.Index(
                        fields=["team"],
                        condition=models.Q(always_include=True),
                        name="bk_source_always_include",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="bk_source_always_include",
                    table_name="posthog_business_knowledge_knowledgesource",
                    columns="(team_id)",
                    where="WHERE always_include = true",
                ),
            ],
        ),
    ]
