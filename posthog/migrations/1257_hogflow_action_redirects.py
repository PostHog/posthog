from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1256_userproductlist_default_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="hogflow",
            name="action_redirects",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
