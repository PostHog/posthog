import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        (
            "customer_analytics",
            "0057_team_customer_analytics_config_activity_event_default",
        ),
        ("posthog", "1376_taggeditem_untrack_legacy_keys"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Built concurrently so the account table stays writable while the indexes are created.
        SafeAddIndexConcurrently(
            model_name="account",
            index=models.Index(
                condition=models.Q(("churned_at__isnull", True)),
                fields=["team", "id"],
                name="ca_account_active_team_id",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="account",
            index=models.Index(
                models.F("team"),
                django.db.models.functions.text.Upper("external_id"),
                name="ca_account_external_id_upper",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="account",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["_properties"],
                name="ca_account_properties_gin",
            ),
        ),
    ]
