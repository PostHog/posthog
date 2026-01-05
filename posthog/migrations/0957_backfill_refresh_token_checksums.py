import hashlib

from django.db import migrations


def backfill_refresh_token_checksums(apps, schema_editor):
    OAuthRefreshToken = apps.get_model("posthog", "OAuthRefreshToken")

    batch_size = 500
    tokens = list(
        OAuthRefreshToken.objects.filter(token_checksum__isnull=True).exclude(token="").only("id", "token")[:batch_size]
    )

    while tokens:
        for token in tokens:
            token.token_checksum = hashlib.sha256(token.token.encode("utf-8")).hexdigest()

        OAuthRefreshToken.objects.bulk_update(tokens, ["token_checksum"], batch_size=batch_size)

        tokens = list(
            OAuthRefreshToken.objects.filter(token_checksum__isnull=True)
            .exclude(token="")
            .only("id", "token")[:batch_size]
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0956_add_refresh_token_checksum"),
    ]

    operations = [
        migrations.RunPython(backfill_refresh_token_checksums, migrations.RunPython.noop),
    ]
