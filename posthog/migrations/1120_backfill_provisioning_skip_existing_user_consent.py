from django.db import migrations


def backfill_skip_consent(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    OAuthApplication.objects.filter(provisioning_auth_method__in=["hmac", "bearer"]).update(
        provisioning_skip_existing_user_consent=True
    )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1119_provisioning_skip_existing_user_consent"),
    ]

    operations = [
        migrations.RunPython(backfill_skip_consent, migrations.RunPython.noop),
    ]
