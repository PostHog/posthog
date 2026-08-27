from django.db import migrations


class Migration(migrations.Migration):
    """Give Postgres a default for provisioning_auth_method, ahead of 1270 dropping it from the
    model state.

    provisioning_auth_method is NOT NULL and its Django ``default=""`` was only ever applied in
    Python, so once the model stops listing the column every INSERT would violate the
    constraint. '' rather than dropping NOT NULL, so rows written by new code still read back
    exactly as the previous release expects while both are live. provisioning_signing_secret is
    already nullable and needs nothing here.

    Alone in its own migration: a RunSQL sharing a file with other operations holds its lock for
    the whole file.
    """

    dependencies = [("posthog", "1268_backfill_is_provisioning_partner")]

    operations = [
        migrations.RunSQL(
            sql="""ALTER TABLE "posthog_oauthapplication" ALTER COLUMN "provisioning_auth_method" SET DEFAULT '';""",
            reverse_sql="""ALTER TABLE "posthog_oauthapplication" ALTER COLUMN "provisioning_auth_method" DROP DEFAULT;""",
        ),
    ]
