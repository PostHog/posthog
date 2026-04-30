from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("dashboards", "0001_migrate_dashboards_models"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="dashboard",
            index=GinIndex(name="idx_dashboard_name_trgm", fields=["name"], opclasses=["gin_trgm_ops"]),
        ),
    ]
