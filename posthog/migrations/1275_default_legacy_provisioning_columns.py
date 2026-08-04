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

COLUMN_DEFAULTS = [(column, "false") for column in BOOLEAN_COLUMNS] + [(column, "''") for column in TEXT_COLUMNS]

SET_DEFAULTS_SQL = 'ALTER TABLE "posthog_oauthapplication" ' + ", ".join(
    f'ALTER COLUMN "{column}" SET DEFAULT {literal}' for column, literal in COLUMN_DEFAULTS
)
DROP_DEFAULTS_SQL = 'ALTER TABLE "posthog_oauthapplication" ' + ", ".join(
    f'ALTER COLUMN "{column}" DROP DEFAULT' for column, _ in COLUMN_DEFAULTS
)


class Migration(migrations.Migration):
    """Give Postgres defaults for the provisioning columns 1276 drops from the model state.

    One ALTER carrying every SET DEFAULT clause rather than one statement per column. These are
    catalog-only changes, but each still needs a brief ACCESS EXCLUSIVE lock, so batching takes
    that lock once instead of eight times - and keeps the file to a single operation, which is
    what the migration risk analyzer asks of one that would otherwise mix several.

    Alone in its own migration: RunSQL sharing a file with other operations holds its lock for
    the whole file.
    """

    dependencies = [("posthog", "1274_backfill_oauth_provisioning_config")]

    operations = [
        migrations.RunSQL(sql=SET_DEFAULTS_SQL, reverse_sql=DROP_DEFAULTS_SQL),
    ]
