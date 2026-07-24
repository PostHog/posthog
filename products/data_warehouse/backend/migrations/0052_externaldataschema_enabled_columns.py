from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0051_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldataschema",
            name="enabled_columns",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
