from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("conversations", "0045_zendesk_ticket_uniq")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(fields=["organization_id"], name="posthog_org_id_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["organization_id", "slack_channel_id"],
                name="posthog_org_slack_ch_idx",
                condition=models.Q(channel_source="slack"),
            ),
        ),
    ]
