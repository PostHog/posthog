from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1351_drop_persistedfolder_table"),
        ("posthog", "1352_temporalschedulerstate"),
    ]

    operations = []
