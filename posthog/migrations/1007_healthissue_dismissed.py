from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1006_resource_transfer_duplicated_resource_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="healthissue",
            name="dismissed",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="healthissue",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("resolved", "Resolved"),
                ],
                default="active",
                max_length=20,
            ),
        ),
    ]
