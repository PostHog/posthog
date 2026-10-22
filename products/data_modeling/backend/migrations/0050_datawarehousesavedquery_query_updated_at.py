from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0049_datamodelingjob_bytes_read"),
    ]

    operations = [
        migrations.AddField(
            model_name="datawarehousesavedquery",
            name="query_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
