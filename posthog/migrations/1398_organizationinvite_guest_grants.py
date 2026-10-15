from django.db import migrations, models

import posthog.models.organization_invite


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1397_organization_guest_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationinvite",
            name="guest_grants",
            field=models.JSONField(
                blank=True,
                default=list,
                null=True,
                validators=[posthog.models.organization_invite.validate_guest_grants],
            ),
        ),
    ]
