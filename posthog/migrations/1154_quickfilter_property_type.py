from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1153_subscription_hourly_frequency")]

    operations = [
        migrations.AddField(
            model_name="quickfilter",
            name="property_type",
            field=models.CharField(
                choices=[
                    ("event", "Event"),
                    ("person", "Person"),
                    ("session", "Session"),
                    ("group", "Group"),
                    ("data_warehouse_person_property", "Data warehouse person property"),
                ],
                default="event",
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name="quickfilter",
            name="group_type_index",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
