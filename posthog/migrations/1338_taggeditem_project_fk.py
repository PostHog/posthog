from django.db import migrations

from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1337_taggeditem_project_unique_constraint"),
    ]

    # NOT VALID skips the child-row scan, so the lock this takes on posthog_project is a brief
    # metadata-only ALTER rather than one held across a full scan. 1339 validates it lock-free.
    operations = [
        AddForeignKeyNotValid(
            model_name="taggeditem",
            name="posthog_taggeditem_project_id_fk",
            column="project_id",
            to_table="posthog_project",
            to_column="id",
        ),
    ]
