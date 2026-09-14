from django.db import migrations, models

import posthog.helpers.encrypted_fields


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1352_email_lookup_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="CLIDeviceAuthorization",
            fields=[
                (
                    "id",
                    models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("device_code", models.CharField(max_length=64, unique=True)),
                ("user_code", models.CharField(max_length=9, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("authorized", "Authorized"), ("consumed", "Consumed")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("user_id", models.BigIntegerField(null=True)),
                ("team_id", models.BigIntegerField(null=True)),
                ("scopes", models.JSONField(default=list)),
                ("label", models.CharField(blank=True, max_length=40)),
                (
                    "personal_api_key_value",
                    posthog.helpers.encrypted_fields.EncryptedCharField(blank=True, max_length=255, null=True),
                ),
                ("expires_at", models.DateTimeField()),
                ("authorized_at", models.DateTimeField(null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [models.Index(fields=["expires_at"], name="posthog_cli_expires_c994fa_idx")],
            },
        ),
        migrations.AlterField(
            model_name="webauthncredential",
            name="verified",
            field=models.BooleanField(
                default=False,
                help_text="Whether the credential has been verified by the user after registration. Verified credentials can log in. An unverified credential can only start email verification for a pending signup.",
            ),
        ),
    ]
