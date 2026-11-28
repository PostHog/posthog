from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("aeo", "0023_check_brand_sentiment"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="aeochecksearch",
            index=models.Index(
                fields=["team_id", "query", "created_at"],
                include=["citation_check_id"],
                name="aeo_check_search_query_idx",
            ),
        ),
    ]
