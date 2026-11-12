from django.db import migrations
from django.db.models.functions import Lower


def backfill_registrations(apps, schema_editor):
    # A support channel in this region is proof that this region registered its domain. Domains
    # that already lost every channel cannot be attributed to a region, so they stay unlisted.
    EmailChannel = apps.get_model("conversations", "EmailChannel")
    MailgunDomainRegistration = apps.get_model("conversations", "MailgunDomainRegistration")
    domains = (
        EmailChannel.objects.filter(kind="support")
        .annotate(domain_lower=Lower("domain"))
        .values_list("domain_lower", flat=True)
        .distinct()
    )
    MailgunDomainRegistration.objects.bulk_create(
        [MailgunDomainRegistration(domain=domain) for domain in domains if domain],
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
