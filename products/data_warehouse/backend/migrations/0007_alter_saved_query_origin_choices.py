from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_warehouse", "0006_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datawarehousesavedquery",
            name="origin",
            field=models.CharField(
                blank=True,
                choices=[
                    ("data_warehouse", "Data Warehouse"),
                    ("endpoint", "Endpoint"),
                    ("managed_viewset", "Managed Viewset"),
                ],
                default=None,
                help_text="Where this SavedQuery is created.",
                null=True,
            ),
        ),
    ]
