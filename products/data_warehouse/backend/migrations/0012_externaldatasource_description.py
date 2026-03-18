from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0011_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="externaldatasource",
            name="description",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
    ]
