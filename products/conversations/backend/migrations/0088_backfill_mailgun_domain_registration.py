from django.db import migrations
from django.db.models import Min
from django.db.models.functions import Lower


def backfill_registrations(apps, schema_editor):
    # A support channel here proves this region registered its domain, close to when the first channel was
    # saved. The cleanup task adopts the Mailgun id only for a registration created near that time.
    EmailChannel = apps.get_model("conversations", "EmailChannel")
    MailgunDomainRegistration = apps.get_model("conversations", "MailgunDomainRegistration")
    first_channels = (
        EmailChannel.objects.filter(kind="support")
        .annotate(domain_lower=Lower("domain"))
        .values("domain_lower")
        .annotate(first_created_at=Min("created_at"))
        .values_list("domain_lower", "first_created_at")
    )
    MailgunDomainRegistration.objects.bulk_create(
        [
            MailgunDomainRegistration(domain=domain, registered_at=first_created_at)
            for domain, first_created_at in first_channels
            if domain
        ],
        ignore_conflicts=True,
        batch_size=1000,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0087_mailgun_domain_registration"),
    ]

    operations = [
        migrations.RunPython(backfill_registrations, migrations.RunPython.noop),
    ]
