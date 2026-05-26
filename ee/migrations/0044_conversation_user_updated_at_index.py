from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("ee", "0043_teamsessionsummariesconfig_custom_tags"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="conversation",
            index=models.Index(
                fields=["user", "-updated_at"],
                name="ee_conv_user_updated_at_idx",
            ),
        ),
    ]
