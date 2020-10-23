from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0091_messagingrecord"),
    ]

    operations = [
        migrations.RunSQL(
            """
            UPDATE "posthog_team"
            SET "name" = 'Default Project';
            """,
            "",
        )
    ]
