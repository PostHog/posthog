from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # DROP INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1339_validate_taggeditem_project_fk"),
    ]

    operations = [
        # This varchar_pattern_ops companion of the slug unique index only serves LIKE and
        # startswith lookups, and every organization slug lookup is an exact match.
        # No SeparateDatabaseAndState wrapper: Django creates the companion implicitly and
        # never records it in migration state.
        DropIndexConcurrently(
            index_name="posthog_organization_slug_01090250_like",
            table_name="posthog_organization",
            columns='("slug" varchar_pattern_ops)',
        ),
    ]
