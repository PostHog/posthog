from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("conversations", "0047_email_delivery_event")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="emailoutboxmessage",
            index=models.Index(fields=["message_id"], name="posthog_con_outbox_msgid_idx"),
        ),
    ]
