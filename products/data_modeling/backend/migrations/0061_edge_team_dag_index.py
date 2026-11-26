from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("data_modeling", "0060_squash_2026_11_02_schema_addons")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="edge",
            index=models.Index(fields=["team", "dag"], name="dmedge_team_dag"),
        ),
    ]
