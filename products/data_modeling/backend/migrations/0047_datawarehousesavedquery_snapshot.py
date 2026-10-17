from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("data_modeling", "0046_dwsavedquery_team_live_created_idx")]

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
        migrations.AlterField(
            model_name="datamodelingjob",
            name="run_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("full_refresh", "Full refresh"),
                    ("incremental", "Incremental"),
                    ("snapshot", "Snapshot"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
