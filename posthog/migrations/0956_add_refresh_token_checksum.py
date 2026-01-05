import hashlib

from django.db import migrations

import oauth2_provider.models


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
    atomic = False  # Don't wrap in transaction - allows concurrent access during backfill

    dependencies = [
        ("posthog", "0955_alter_organization_is_ai_data_processing_approved"),
    ]

    operations = [
        # Step 1: Add nullable field with index (fast, no lock)
        migrations.AddField(
            model_name="oauthrefreshtoken",
            name="token_checksum",
            field=oauth2_provider.models.TokenChecksumField(blank=True, db_index=True, max_length=64, null=True),
        ),
        # Step 2: Backfill existing tokens (batched, non-blocking)
        migrations.RunPython(backfill_refresh_token_checksums, migrations.RunPython.noop),
    ]
