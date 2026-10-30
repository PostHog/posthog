from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("ai_observability", "0069_offline_evaluation_usage_ledger")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="offlineexperimentitem",
            index=models.Index(
                fields=["payload_expires_at", "id"],
                condition=models.Q(payload_state="available"),
                name="aio_item_payload_expiry_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="offlineevaluationresult",
            index=models.Index(
                fields=["payload_expires_at", "id"],
                condition=models.Q(payload_state="available"),
                name="aio_result_payload_expiry_idx",
            ),
        ),
    ]
