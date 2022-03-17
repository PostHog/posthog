# Generated by Django 3.2.5 on 2022-03-16 08:36

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone

import posthog.models.organization_domain
import posthog.models.utils


def migrate_domain_whitelist(apps, schema_editor):
    Organization = apps.get_model("posthog", "Organization")
    OrganizationDomain = apps.get_model("posthog", "OrganizationDomain")

    for org in Organization.objects.exclude(domain_whitelist=[]):
        for domain in org.domain_whitelist:
            OrganizationDomain.objects.create(domain=domain, verified_at=timezone.now(), jit_provisioning_enabled=True)


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0221_add_activity_log_model"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationDomain",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("domain", models.CharField(max_length=128, unique=True)),
                (
                    "verification_challenge",
                    models.CharField(
                        default=posthog.models.organization_domain.generate_verification_challenge, max_length=128
                    ),
                ),
                ("verified_at", models.DateTimeField(blank=True, default=None, null=True)),
                ("last_verification_retry", models.DateTimeField(blank=True, default=None, null=True)),
                (
                    "jit_provisioning_enabled",
                    models.BooleanField(default=False),
                ),  # Just-in-time automatic provisioning (user accounts are created on the respective org when logging in with any SSO provider)
                ("sso_enforcement", models.CharField(blank=True, max_length=28)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="domains", to="posthog.organization"
                    ),
                ),
            ],
            options={"abstract": False, "verbose_name": "domain"},
        ),
        migrations.RunPython(migrate_domain_whitelist, migrations.RunPython.noop),
    ]
