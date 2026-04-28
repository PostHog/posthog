from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0048_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externaldataschema",
            name="latest_error",
            field=models.TextField(
                blank=True,
                help_text="The latest error that occurred when syncing this schema.",
                null=True,
            ),
        ),
    ]
