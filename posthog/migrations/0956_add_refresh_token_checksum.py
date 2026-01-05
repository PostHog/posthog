from django.db import migrations

import oauth2_provider.models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0955_alter_organization_is_ai_data_processing_approved"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthrefreshtoken",
            name="token_checksum",
            field=oauth2_provider.models.TokenChecksumField(blank=True, db_index=True, max_length=64, null=True),
        ),
    ]
