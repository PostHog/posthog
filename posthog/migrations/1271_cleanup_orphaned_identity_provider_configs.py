from django.db import migrations


def delete_orphaned_identity_provider_configs(apps, schema_editor):
    IdentityProviderConfig = apps.get_model("posthog", "IdentityProviderConfig")
    IdentityProviderConfig.objects.filter(domains__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1270_untrack_provisioning_auth_columns"),
    ]

    operations = [
        migrations.RunPython(
            delete_orphaned_identity_provider_configs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
