from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1396_events_retention_config"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organizationmembership",
            name="level",
            field=models.PositiveSmallIntegerField(
                choices=[(0, "guest"), (1, "member"), (8, "administrator"), (15, "owner")], default=1
            ),
        ),
        migrations.AlterField(
            model_name="organizationinvite",
            name="level",
            field=models.PositiveSmallIntegerField(
                choices=[(0, "guest"), (1, "member"), (8, "administrator"), (15, "owner")], default=1
            ),
        ),
    ]
