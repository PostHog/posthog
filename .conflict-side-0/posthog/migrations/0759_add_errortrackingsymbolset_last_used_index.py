from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0758_alter_externaldatasource_source_type"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="errortrackingsymbolset",
            index=models.Index(fields=["last_used"], name="posthog_err_last_us_c924f6_idx"),
        ),
    ]

    # Required for concurrent operations
    atomic = False
