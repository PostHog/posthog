from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "customer_analytics",
            "0058_accountrelationshipdefinition_claim_saved_query_sha256",
        )
    ]

    operations = [
        migrations.AddField(
            model_name="teamcustomeranalyticsconfig",
            name="default_pinned_properties",
            field=models.JSONField(default=list),
        ),
    ]
