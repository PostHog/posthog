from django.db import migrations

from posthog.migration_helpers import AddForeignKeyNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1372_taggeditem_hog_flow_unique_constraint"),
    ]

    # NOT VALID skips the child-row scan, so the lock this takes on posthog_hogflow is a brief
    # metadata-only ALTER rather than one held across a full scan. 1374 validates it lock-free.
    operations = [
        AddForeignKeyNotValid(
            model_name="taggeditem",
            name="posthog_taggeditem_hog_flow_id_fk",
            column="hog_flow_id",
            to_table="posthog_hogflow",
            to_column="id",
        ),
    ]
