from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("customer_analytics", "0036_feature_request_multi_account_evidence"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="featurerequestaccountlink",
            index=models.Index(
                fields=["team", "feature_request", "unlinked_at"],
                name="fr_link_request_active_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="featurerequestaccountlink",
            index=models.Index(
                fields=["team", "account", "unlinked_at"],
                name="fr_link_account_active_idx",
            ),
        ),
    ]
