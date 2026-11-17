from django.conf import settings
from django.db import migrations


def delete_eu_tokens(apps, schema_editor):
    # Verification tokens are issued in PostHog US only, and EU now confirms partners' tokens with US. The tokens
    # EU issued before that linked no partner, and nothing would check them again.
    if settings.CLOUD_DEPLOYMENT != "EU":
        return
    apps.get_model("posthog", "CIMDVerificationToken").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1441_oauthapplication_organization_link_region"),
    ]

    operations = [
        migrations.RunPython(delete_eu_tokens, migrations.RunPython.noop, elidable=True),
    ]
