from django.conf import settings
from django.db import migrations

WIZARD_RUN_WRITE_SCOPE = "wizard_run:write"
WIZARD_CLI_CLIENT_IDS = (
    "c4Rdw8DIxgtQfA80IiSnGKlNX8QN00cFWF00QQhM",  # US
    "bx2C5sZRN03TkdjraCcetvQFPGH6N2Y9vRLkcKEy",  # EU
)


def add_wizard_run_scope(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    client_ids = {*WIZARD_CLI_CLIENT_IDS, settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID} - {""}
    for app in OAuthApplication.objects.using(schema_editor.connection.alias).filter(client_id__in=client_ids):
        if WIZARD_RUN_WRITE_SCOPE not in app.scopes:
            app.scopes = [*(app.scopes or ["@default"]), WIZARD_RUN_WRITE_SCOPE]
            app.save(update_fields=["scopes"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1386_taggeditem_drop_legacy_columns"),
    ]

    operations = [
        migrations.RunPython(add_wizard_run_scope, migrations.RunPython.noop),
    ]
