import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [("posthog", "1286_cleanup_orphaned_identity_provider_configs")]

    operations = [
        migrations.CreateModel(
            name="LinkedIdentityProviderConfig",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "identity_provider_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="linked_identity_provider_configs",
                        to="posthog.identityproviderconfig",
                    ),
                ),
                (
                    "organization_domain",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="linked_identity_provider_configs",
                        to="posthog.organizationdomain",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization_domain", "identity_provider_config"),
                        name="unique_linked_identity_provider_config",
                    )
                ],
            },
        ),
    ]
