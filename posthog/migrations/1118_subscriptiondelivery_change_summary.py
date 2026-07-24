from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1117_role_external_reference")]

    operations = [
        migrations.AddField(
            model_name="subscriptiondelivery",
            name="change_summary",
            field=models.TextField(blank=True, null=True),
        ),
    ]
