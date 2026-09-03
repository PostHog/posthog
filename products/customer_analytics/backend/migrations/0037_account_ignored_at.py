from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0036_custompropertysyncrun_saved_query_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="ignored_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
