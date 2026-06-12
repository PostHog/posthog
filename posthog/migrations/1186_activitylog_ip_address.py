from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1185_fix_non_list_test_account_filters"),
    ]

    operations = [
        migrations.AddField(
            model_name="activitylog",
            name="ip_address",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
    ]
