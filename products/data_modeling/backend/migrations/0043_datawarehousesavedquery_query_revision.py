import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0042_dwsavedquery_team_live_matvw_idx"),
    ]

    operations = [
        # Added without a default so existing rows stay NULL instead of all receiving one shared
        # value; the column is metadata-only on Postgres this way.
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="query_revision",
            field=models.UUIDField(blank=True, null=True),
        ),
        # A Python-level default only; this emits no SQL.
        migrations.AlterField(
            model_name="datawarehousesavedquery",
            name="query_revision",
            field=models.UUIDField(blank=True, default=uuid.uuid4, null=True),
        ),
    ]
