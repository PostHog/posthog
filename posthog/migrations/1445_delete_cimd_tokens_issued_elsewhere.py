from django.conf import settings
from django.db import migrations


def delete_tokens_issued_here(apps, schema_editor):
    # An instance with an issuer configured confirms partners' tokens with the issuer and never reads its own. Tokens
    # it created before that linked no partner, and nothing would check them again.
    if not settings.CIMD_VERIFICATION_TOKEN_ISSUER_URL:
        return
    apps.get_model("posthog", "CIMDVerificationToken").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1444_oauthapplication_organization_link_issuer"),
    ]

    operations = [
        migrations.RunPython(delete_tokens_issued_here, migrations.RunPython.noop, elidable=True),
    ]
