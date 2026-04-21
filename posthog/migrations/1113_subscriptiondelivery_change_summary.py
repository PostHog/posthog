from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1112_datadeletionrequest_delete_all_events")]

    operations = [
        migrations.AddField(
            model_name="subscriptiondelivery",
            name="change_summary",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
