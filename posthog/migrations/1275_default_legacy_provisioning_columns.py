from django.db import migrations

# Every retired column that is NOT NULL. Their Django ``default=`` was only ever applied in
# Python, so once the model stops listing them every INSERT would violate the constraint.
# Defaults rather than dropping NOT NULL, so rows written by new code still read back exactly as
# the previous release expects while both are live.
BOOLEAN_COLUMNS = [
    "provisioning_active",
    "provisioning_can_create_accounts",
    "provisioning_can_issue_deep_links",
    "provisioning_can_provision_resources",
    "provisioning_disabled",
    "provisioning_skip_existing_user_consent",
]
TEXT_COLUMNS = [
    "provisioning_partner_type",
    "provisioning_rate_limit_account_requests_source",
]

# provisioning_issues_personal_api_key already has a Postgres default (it was added with
# db_default), and the five rate-limit columns are nullable, so neither needs anything here.


def _set_default(column: str, literal: str) -> migrations.RunSQL:
    return migrations.RunSQL(
        sql=f"""ALTER TABLE "posthog_oauthapplication" ALTER COLUMN "{column}" SET DEFAULT {literal};""",
        reverse_sql=f"""ALTER TABLE "posthog_oauthapplication" ALTER COLUMN "{column}" DROP DEFAULT;""",
    )


class Migration(migrations.Migration):
    """Give Postgres defaults for the provisioning columns 1276 drops from the model state.

    Alone in its own migration: RunSQL sharing a file with other operations holds its lock for
    the whole file. These are catalog-only ALTERs on a small table, so they are cheap, but they
    still take a brief ACCESS EXCLUSIVE lock each.
    """

    dependencies = [("posthog", "1274_backfill_oauth_provisioning_config")]

    operations = [
        *[_set_default(column, "false") for column in BOOLEAN_COLUMNS],
        *[_set_default(column, "''") for column in TEXT_COLUMNS],
    ]
