from django.db import migrations

from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1348_taggeditem_experiment_unique_constraint"),
    ]

    # NOT VALID skips the child-row scan, so the lock this takes on posthog_experiment is a brief
    # metadata-only ALTER rather than one held across a full scan. 1350 validates it lock-free.
    operations = [
        AddForeignKeyNotValid(
            model_name="taggeditem",
            name="posthog_taggeditem_experiment_id_fk",
            column="experiment_id",
            to_table="posthog_experiment",
            to_column="id",
        ),
    ]
