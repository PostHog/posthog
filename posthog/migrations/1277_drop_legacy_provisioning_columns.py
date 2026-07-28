from django.db import migrations

# Every provisioning column this stack stopped tracking. 1270 untracked the two auth columns
# superseded by is_provisioning_partner plus client_type; 1276 untracked the per-capability and
# per-quota columns superseded by provisioning_config.
DROPPED_COLUMNS = [
    "provisioning_auth_method",
    "provisioning_signing_secret",
    "provisioning_active",
    "provisioning_can_create_accounts",
    "provisioning_can_issue_deep_links",
    "provisioning_can_provision_resources",
    "provisioning_disabled",
    "provisioning_issues_personal_api_key",
    "provisioning_partner_type",
    "provisioning_rate_limit_account_requests",
    "provisioning_rate_limit_account_requests_source",
    "provisioning_rate_limit_github_grants",
    "provisioning_rate_limit_resource_creates",
    "provisioning_rate_limit_token_exchanges",
    "provisioning_rate_limit_wizard_runs",
    "provisioning_skip_existing_user_consent",
]

# Re-added on reverse so a rolled-back schema still matches what the pre-1270 code selects.
# Types and defaults only - the values are gone, and restoring them means replaying the
# backfills in 1268 and 1274 from provisioning_config and is_provisioning_partner.
REVERSE_COLUMN_TYPES = {
    "provisioning_auth_method": "varchar(20) NOT NULL DEFAULT ''",
    "provisioning_signing_secret": "text NULL",
    "provisioning_active": "boolean NOT NULL DEFAULT false",
    "provisioning_can_create_accounts": "boolean NOT NULL DEFAULT false",
    "provisioning_can_issue_deep_links": "boolean NOT NULL DEFAULT false",
    "provisioning_can_provision_resources": "boolean NOT NULL DEFAULT false",
    "provisioning_disabled": "boolean NOT NULL DEFAULT false",
    "provisioning_issues_personal_api_key": "boolean NOT NULL DEFAULT false",
    "provisioning_partner_type": "varchar(50) NOT NULL DEFAULT ''",
    "provisioning_rate_limit_account_requests": "integer NULL",
    "provisioning_rate_limit_account_requests_source": "varchar(24) NOT NULL DEFAULT ''",
    "provisioning_rate_limit_github_grants": "integer NULL",
    "provisioning_rate_limit_resource_creates": "integer NULL",
    "provisioning_rate_limit_token_exchanges": "integer NULL",
    "provisioning_rate_limit_wizard_runs": "integer NULL",
    "provisioning_skip_existing_user_consent": "boolean NOT NULL DEFAULT false",
}

DROP_SQL = 'ALTER TABLE "posthog_oauthapplication" ' + ", ".join(
    f'DROP COLUMN IF EXISTS "{column}"' for column in DROPPED_COLUMNS
)
REVERSE_SQL = 'ALTER TABLE "posthog_oauthapplication" ' + ", ".join(
    f'ADD COLUMN IF NOT EXISTS "{column}" {REVERSE_COLUMN_TYPES[column]}' for column in DROPPED_COLUMNS
)


class Migration(migrations.Migration):
    """Drop the provisioning columns Django stopped tracking in 1270 and 1276.

    Columns untracked in PostHog/posthog#74089 (provisioning_auth_method,
    provisioning_signing_secret) and PostHog/posthog#74351 (the rest).

    BEFORE MERGING, confirm both are deployed and have been through a full deploy cycle. Nothing
    here can check that: a migration only sees the database, not which release the pods are
    running, and on a fresh database 1276 and 1277 apply seconds apart, so a timing guard would
    either break new installs or leave their schema permanently divergent. It is a release
    ordering constraint, and the reviewer is the only thing enforcing it.

    Merging early breaks reads, not writes, and breaks them everywhere: a pod on the previous
    release still names every one of these columns in its SELECT, so each one errors on an
    undefined column. That is the login path, the OAuth path and the whole provisioning
    namespace, for as long as the old pods are up.

    One ALTER with every DROP clause rather than one statement per column: each drop is a
    catalog-only change needing an ACCESS EXCLUSIVE lock, so batching them takes that lock once
    instead of sixteen times. posthog_oauthapplication is small and not one of the hot tables,
    so the lock window is short.

    IF EXISTS on each clause keeps this idempotent under bin/migrate retries.
    """

    dependencies = [("posthog", "1276_untrack_legacy_provisioning_columns")]

    operations = [
        migrations.RunSQL(sql=DROP_SQL, reverse_sql=REVERSE_SQL),
    ]
