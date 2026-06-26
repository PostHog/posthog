from django.db import migrations


def backfill_identity_verified(apps, schema_editor):
    # Slack/Teams/GitHub tickets originate from signature-validated webhooks, so their
    # identity is server-attested purely by channel — backfill those to verified.
    # Everything else (widget HMAC, email SPF) was assessed per-request and isn't
    # recoverable for historical rows, so it stays NULL ("unknown") rather than False.
    Ticket = apps.get_model("conversations", "Ticket")
    Ticket.objects.filter(channel_source__in=["slack", "teams", "github"]).update(identity_verified=True)


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0042_ticket_identity_verified"),
    ]

    operations = [
        migrations.RunPython(backfill_identity_verified, migrations.RunPython.noop),
    ]
