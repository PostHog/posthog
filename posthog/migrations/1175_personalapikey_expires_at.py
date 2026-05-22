from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1174_taggeditem_account_unique_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="personalapikey",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
