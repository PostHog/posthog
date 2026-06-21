# Adds a per-document classification attempt counter so the safety classifier
# can fail CLOSED (leave a doc `unknown`/excluded on a model block/error)
# without the coordinator re-queuing the same doc on every hourly pass forever.
# Additive scalar column with a Postgres-level default — safe to add online.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0006_bk_source_refresh_due_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgedocument",
            name="classification_attempts",
            field=models.PositiveSmallIntegerField(default=0, db_default=0),
        ),
    ]
