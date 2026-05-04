from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1139_alter_datadeletionrequest_person_distinct_ids_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="enabled",
            field=models.BooleanField(default=True),
        ),
    ]
