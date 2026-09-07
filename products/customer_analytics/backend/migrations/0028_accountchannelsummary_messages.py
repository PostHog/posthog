from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0027_accountchannelsummary_validate_fks"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountchannelsummary",
            name="messages",
            field=models.JSONField(default=list),
        ),
    ]
