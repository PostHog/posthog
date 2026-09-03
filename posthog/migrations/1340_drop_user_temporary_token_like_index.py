from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    """Drop the unused `temporary_token` LIKE companion index.

    Postgres creates this `varchar_pattern_ops` index next to the unique index because the
    field declares `unique=True`. It only serves LIKE and startswith lookups, and there are
    none: the toolbar moved to OAuth, 0984 set every value to NULL, and the one remaining
    reader filters on isnull. The plain unique index stays, because the field is still unique.
    """

    atomic = False

    dependencies = [
        ("posthog", "1339_validate_taggeditem_project_fk"),
    ]

    operations = [
        # No SeparateDatabaseAndState wrapper: Django never recorded this
        # auto-generated `_like` companion in migration state.
        DropIndexConcurrently(
            index_name="posthog_user_temporary_token_9d7b57f3_like",
            table_name="posthog_user",
            columns='("temporary_token" varchar_pattern_ops)',
        ),
    ]
