from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("customer_analytics", "0059_account_view")]

    operations = [
        migrations.AddField(
            model_name="teamcustomeranalyticsconfig",
            name="default_pinned_properties",
            field=models.JSONField(default=list),
        ),
    ]
