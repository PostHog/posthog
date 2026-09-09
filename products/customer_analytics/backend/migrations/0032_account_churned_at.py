from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0031_featurerequest_featurerequestproductarea_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="churned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
