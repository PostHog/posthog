from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so the build takes no ACCESS EXCLUSIVE lock on oauthaccesstoken. A
    # concurrent build cannot run in a transaction, so the migration is non-atomic.
    atomic = False

    dependencies = [
        ("posthog", "1340_drop_userproductlist_reason_columns"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="oauthaccesstoken",
            index=models.Index(fields=["expires"], name="oauthaccesstoken_expires_idx"),
        ),
    ]
