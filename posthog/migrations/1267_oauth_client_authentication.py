from django.db import migrations, models


class Migration(migrations.Migration):
    """Add the columns that replace provisioning_auth_method: is_provisioning_partner, and
    jwks_uri for private_key_jwt clients.

    Schema only. The backfill lands in 1267 and the retirement of the old columns in 1268,
    because a data migration in the same file as schema changes holds its locks for the whole
    file. Both new columns are additive and nullable-or-defaulted, so this half is safe to run
    on its own and leaves the previous release working untouched.
    """

    dependencies = [("posthog", "1266_comment_convo_content_trgm")]

    operations = [
        migrations.AddField(
            model_name="oauthapplication",
            name="is_provisioning_partner",
            field=models.BooleanField(
                db_default=False,
                default=False,
                help_text=(
                    "Whether this app may act as an agentic provisioning partner. How it authenticates "
                    "follows from client_type, so there is no separate provisioning auth method."
                ),
            ),
        ),
        migrations.AddField(
            model_name="oauthapplication",
            name="jwks_uri",
            field=models.URLField(
                blank=True,
                help_text=(
                    "HTTPS URL serving the client's public keys as a JWK Set. Setting this on a "
                    "confidential client switches it to private_key_jwt authentication (RFC 7523): it "
                    "signs an assertion we verify against these keys instead of holding a shared secret."
                ),
                max_length=2048,
                null=True,
            ),
        ),
    ]
