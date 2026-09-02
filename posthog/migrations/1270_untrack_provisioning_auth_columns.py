from django.db import migrations


class Migration(migrations.Migration):
    """Stop tracking provisioning_auth_method and provisioning_signing_secret in Django state.

    Runs after 1269 so Postgres already has a default for provisioning_auth_method by the time
    the model stops listing it, and after 1268 so the backfill still had the column in state to
    read from.
    """

    dependencies = [("posthog", "1269_retire_provisioning_auth_method")]

    operations = [
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
    ]
