from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_modeling", "0042_dwsavedquery_team_live_matvw_idx")]

    operations = [
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="snapshot_config",
            field=models.JSONField(
                blank=True,
                default=None,
                help_text="Snapshot materialization settings: unique_key. Null means snapshot mode is disabled.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="snapshot_state",
            field=models.JSONField(
                blank=True,
                default=None,
                help_text="System-written snapshot generation and observation state.",
                null=True,
            ),
        ),
    ]
