from django.db import migrations

import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1034_taggeditem_ticket_unique_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="encrypted_inputs",
            field=posthog.helpers.encrypted_fields.EncryptedJSONStringField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hogflow",
            name="draft_encrypted_inputs",
            field=posthog.helpers.encrypted_fields.EncryptedJSONStringField(blank=True, null=True),
        ),
    ]
