from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cdp", "0003_hog_function_drafts"),
    ]

    operations = [
        # No SeparateDatabaseAndState wrapper: Django never recorded this
        # auto-generated `_like` companion in migration state.
        DropIndexConcurrently(
            index_name="ee_hook_id_d4e48550_like",
            table_name="ee_hook",
            columns='("id" varchar_pattern_ops)',
        ),
    ]
