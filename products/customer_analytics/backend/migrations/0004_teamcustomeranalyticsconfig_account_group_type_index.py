from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0003_customer_journey"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamcustomeranalyticsconfig",
            name="account_group_type_index",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
