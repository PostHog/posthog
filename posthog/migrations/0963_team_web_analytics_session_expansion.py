from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0962_webanalyticsfilterpreset"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="web_analytics_session_expansion_enabled",
            field=models.BooleanField(default=True, null=True),
        ),
    ]
