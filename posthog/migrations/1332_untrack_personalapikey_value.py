from django.db import migrations


class Migration(migrations.Migration):
    """Stop tracking the deprecated value column on PersonalAPIKey in Django state.

    0260_pak_v2 hashed every key into secure_value and set value to NULL back in 2022, and no
    code reads or writes it since. Postgres still keeps a varchar_pattern_ops LIKE index next to
    the unique index, so the dead column also carries a dead index.

    State-only: the column stays in Postgres so a rollback to the previous release still finds
    it, and so no query against a dropped column can 500 during the deploy window. Drop the
    column itself in a later release, once no deployed code references it.
    """

    dependencies = [("posthog", "1331_messagingrecord_campaign_key_idx")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="personalapikey",
                    name="value",
                ),
            ],
            database_operations=[],
        ),
    ]
