from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "1331_messagingrecord_campaign_key_idx")]

    operations = [
        # State-only: the table lives in the persons database, whose schema is owned by
        # rust/persons_migrations. The model has had no reader or writer since the
        # plugin-server override writer was removed. The unused index is dropped there;
        # any DROP TABLE also happens there once retention is confirmed.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="FlatPersonOverride",
                ),
            ],
        ),
    ]
