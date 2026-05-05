from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0050_alter_externaldataschema_latest_error"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="synced_columns",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
