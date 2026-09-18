from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0042_dwsavedquery_team_live_matvw_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="node",
            name="last_demand_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When a query last read this model or one of its descendants, taken from the ClickHouse query log",
                null=True,
            ),
        ),
    ]
