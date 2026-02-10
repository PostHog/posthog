from django.db import migrations


def clean_up_stale_alert_subscriptions(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            DELETE FROM posthog_alertsubscription
            WHERE id IN (
                SELECT sub.id
                FROM posthog_alertsubscription sub
                JOIN posthog_alertconfiguration ac ON ac.id = sub.alert_configuration_id
                JOIN posthog_team t ON t.id = ac.team_id
                LEFT JOIN posthog_organizationmembership om
                    ON om.user_id = sub.user_id
                    AND om.organization_id = t.organization_id
                WHERE om.id IS NULL
            )
        """)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1000_create_healthissue_table"),
    ]

    operations = [
        migrations.RunPython(
            clean_up_stale_alert_subscriptions,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
