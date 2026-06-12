import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1142_alter_batchexportdestination_type_and_more"),
        ("notebooks", "0003_add_kernel_timeouts"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharingconfiguration",
            name="notebook",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sharing_configurations",
                to="notebooks.notebook",
            ),
        ),
    ]
