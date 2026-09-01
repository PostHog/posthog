from django.db import migrations, models

from posthog.migration_helpers.concurrent_index import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("annotations", "0003_annotation_hidden_in_user_interface"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="annotation",
            index=models.Index(
                condition=models.Q(("deleted", False)),
                fields=["team", "-date_marker"],
                name="annotation_team_date_marker",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="annotation",
            index=models.Index(
                condition=models.Q(("deleted", False), ("scope", "organization")),
                fields=["organization", "-date_marker"],
                name="annotation_org_date_marker",
            ),
        ),
    ]
