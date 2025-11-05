from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Test migration to verify analyzer correctly flags nullable field additions.

    This migration is similar to 0900 which caused the production incident on Nov 4, 2025.
    It should be flagged as NEEDS_REVIEW (score 1) with guidance about high-traffic tables.
    """

    dependencies = [
        ("posthog", "0900_team_receive_org_level_activity_logs"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="test_nullable_field",
            field=models.CharField(max_length=255, blank=True, null=True),
        ),
    ]
