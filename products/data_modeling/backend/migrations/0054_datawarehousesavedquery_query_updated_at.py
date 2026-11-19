from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0053_job_team_created_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="query_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
