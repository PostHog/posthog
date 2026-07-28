from django.db import migrations, models

# Methods whose apps become provisioning partners under the new boolean. Chosen to preserve
# today's behavior exactly: these are the two values the resource endpoints currently accept
# outstanding access tokens for. "hmac" is excluded because those apps already fail closed
# everywhere, and "" was never a partner.
PARTNER_AUTH_METHODS = ["pkce", "bearer"]


def backfill_is_provisioning_partner(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    OAuthApplication.objects.filter(provisioning_auth_method__in=PARTNER_AUTH_METHODS).update(
        is_provisioning_partner=True
    )


class Migration(migrations.Migration):
    """Replace provisioning_auth_method with is_provisioning_partner plus real OAuth client
    authentication (client_type, and jwks_uri for private_key_jwt).

    Ordering matters within this migration: the backfill must run while
    provisioning_auth_method is still in the model state, and Postgres must be given a
    default for it before the field leaves that state.
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
        migrations.RunPython(backfill_is_provisioning_partner, migrations.RunPython.noop, elidable=True),
        # provisioning_auth_method is NOT NULL and its Django `default=""` was only ever applied
        # in Python, so once the model stops listing the column every INSERT would violate the
        # constraint. Give Postgres the default before that happens. '' rather than dropping NOT
        # NULL so rows written by new code still read back exactly as the previous release
        # expects while both are live. provisioning_signing_secret is already nullable.
        migrations.RunSQL(
            sql="""ALTER TABLE "posthog_oauthapplication" ALTER COLUMN "provisioning_auth_method" SET DEFAULT '';""",
            reverse_sql="""ALTER TABLE "posthog_oauthapplication" ALTER COLUMN "provisioning_auth_method" DROP DEFAULT;""",
        ),
        # State-only: Django stops tracking these two columns, but they stay in Postgres so a
        # rollback to the previous release still finds them, and so no read of a dropped column
        # can 500 during the deploy window. provisioning_auth_method is superseded by
        # is_provisioning_partner plus client_type; provisioning_signing_secret held the per-app
        # HMAC secret, which has no readers left (the Stripe partner surface signs against
        # settings.STRIPE_SIGNING_SECRET instead). Drop the columns themselves in a later
        # release, once no deployed code references them.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="oauthapplication",
                    name="provisioning_auth_method",
                ),
                migrations.RemoveField(
                    model_name="oauthapplication",
                    name="provisioning_signing_secret",
                ),
            ],
            database_operations=[],
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
