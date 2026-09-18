from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1368_sessionrecording_untrack_lts_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="tag",
            name="pinned",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
