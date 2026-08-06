from django.db import migrations

RETIRED_COLUMNS = [
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


class Migration(migrations.Migration):
    """Stop tracking the per-capability provisioning columns in Django state.

    Runs after 1275 so Postgres already has defaults for the NOT NULL ones by the time the model
    stops listing them, and after 1274 so the backfill still had them in state to read from.

    State-only: the columns stay in Postgres so a rollback to the previous release still finds
    them, and so no read of a dropped column can 500 during the deploy window. Drop them for
    real in a later release, once no deployed code references them.
    """

    dependencies = [("posthog", "1275_default_legacy_provisioning_columns")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="oauthapplication", name=column) for column in RETIRED_COLUMNS
            ],
            database_operations=[],
        ),
    ]
