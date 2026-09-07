from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0049_validate_customer_task_foreign_keys"),
    ]

    operations = [
        migrations.AddField(
            model_name="customerprofileconfig",
            name="pinned_properties",
            field=models.JSONField(default=list),
        ),
    ]
