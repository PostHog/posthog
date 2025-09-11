import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0257_add_default_checked_for_test_filters_on_team"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="recording_domains",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=200, null=True),
                blank=True,
                null=True,
                size=None,
            ),
        ),
    ]
