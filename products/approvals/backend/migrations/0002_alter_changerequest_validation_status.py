from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="changerequest",
            name="validation_status",
            field=models.CharField(
                choices=[
                    ("valid", "Valid"),
                    ("invalid", "Invalid"),
                    ("stale", "Stale (resource changed)"),
                ],
                default="valid",
                max_length=16,
            ),
        ),
    ]
