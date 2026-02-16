from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1005_objectmediapreview_and_more"),
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
