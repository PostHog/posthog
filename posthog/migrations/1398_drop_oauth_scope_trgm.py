from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1397_uploaded_media_dimensions_and_archive"),
    ]

    operations = [
        # 1320 dropped this index, but the squashed 1345 built it again on existing
        # databases. Django state does not track it, so no SeparateDatabaseAndState.
        DropIndexConcurrently(
            index_name="oauthaccesstoken_scope_trgm",
            table_name="posthog_oauthaccesstoken",
            columns="(scope gin_trgm_ops)",
            using="gin",
            where="WHERE application_id IS NOT NULL",
        ),
    ]
