from django.db import migrations

import oauth2_provider.models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1219_filesystemfoldercontextgeneration"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthrefreshtoken",
            name="token_checksum",
            field=oauth2_provider.models.TokenChecksumField(blank=True, db_index=True, max_length=64, null=True),
        ),
    ]
