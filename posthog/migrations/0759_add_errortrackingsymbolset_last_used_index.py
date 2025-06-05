from django.db import migrations, models
from django.contrib.postgres.operations import AddIndexConcurrently


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0758_alter_externaldatasource_source_type"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="errortrackingsymbolset",
            index=models.Index(fields=["last_used"], name="idx_error_tracking_symbol_set_last_used"),
        ),
    ]

    # Required for concurrent operations
    atomic = False
