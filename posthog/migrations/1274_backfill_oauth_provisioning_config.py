from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def backfill_provisioning_config(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")

    # Pinned to the alias `migrate` is running on rather than letting the router pick. bin/migrate
    # uses `default_direct`, which bypasses PgBouncer and therefore has server-side cursors
    # enabled; the router would send this to `default`, where DISABLE_SERVER_SIDE_CURSORS makes
    # .iterator() buffer the whole result set client-side and puts the writes in their own
    # transaction outside the migration's.
    db_alias = schema_editor.connection.alias

    # Every row, deliberately unfiltered. Provisioning state is spread over fourteen columns and
    # several were set by migrations keyed on things unrelated to whether an app looks like a
    # partner today, so any filter cheap enough to write here skips rows that carry state. A row
    # with no state maps to a config that grants nothing, which is what the column's `{}` default
    # already reads as, so writing it everywhere costs a batched update and loses nothing.
    candidates = OAuthApplication.objects.using(db_alias).order_by("pk")

    # Collected while iterating rather than in a second query, which would mean a second pass over
    # the table.
    lost_wizard_runs = []
    updated = []
    for app in candidates.iterator(chunk_size=BATCH_SIZE):
        # provisioning_partner_type was doing double duty as the marker for a partner PostHog
        # vouched for, and it is the only signal available here for who keeps the two elevated
        # capabilities. A self-registered CIMD partner never had one set, so it does not get
        # them - which is the restriction this change exists to introduce.
        vouched_for = bool(app.provisioning_partner_type)

        # Two of the capabilities below read permissively on a row nobody ever configured:
        # provisioning_can_provision_resources was added with `default=True`, and the old
        # github-grants gate passed anything non-CIMD. Both endpoint families already require
        # is_provisioning_partner before they consult the capability (authentication.py, in
        # `_resolve_partner` and `ProvisioningBearerAuthentication`), so requiring it here too
        # changes no request's outcome - it keeps the backfill from writing a granted-looking
        # value onto every ordinary OAuth app in the table, which would read as a grant in the
        # admin and become load-bearing the day a gate stopped checking the flag.
        is_partner = app.is_provisioning_partner

        app._provisioning_config = {
            "active": app.provisioning_active,
            # Never conditioned on is_provisioning_partner: clearing that flag is part of how an
            # admin kills a partner, and the kill switch has to outlive it or the next CIMD
            # registration re-grants the partner its defaults.
            "disabled": app.provisioning_disabled,
            "can_create_accounts": app.provisioning_can_create_accounts,
            "can_provision_resources": is_partner and app.provisioning_can_provision_resources,
            # The old gate was `is_cimd_client and not provisioning_partner_type`, so a non-CIMD
            # partner passed on being admin-created alone. Both collapse to one capability, and a
            # partner type still carries the grant on its own - 1268 only flagged pkce and bearer
            # apps, so a vouched-for partner on another auth method must not lose it here.
            "can_use_github_grants": vouched_for or (is_partner and not app.is_cimd_client),
            # The wizard endpoints carried no gate of their own, so any active partner with
            # can_provision_resources could start a cloud run, self-registered CIMD partners
            # included. Narrowed to vouched-for partners here.
            "can_start_wizard_runs": vouched_for and app.provisioning_can_provision_resources,
            "can_issue_deep_links": app.provisioning_can_issue_deep_links,
            "skip_existing_user_consent": app.provisioning_skip_existing_user_consent,
            "issues_personal_api_key": app.provisioning_issues_personal_api_key,
            "rate_limits": {
                "account_requests": app.provisioning_rate_limit_account_requests,
                "token_exchanges": app.provisioning_rate_limit_token_exchanges,
                "resource_creates": app.provisioning_rate_limit_resource_creates,
                "github_grants": app.provisioning_rate_limit_github_grants,
                "wizard_runs": app.provisioning_rate_limit_wizard_runs,
            },
            "rate_limit_source": app.provisioning_rate_limit_account_requests_source,
        }
        # Could start a cloud run before this migration and cannot after it.
        if app.provisioning_active and app.provisioning_can_provision_resources and not vouched_for:
            lost_wizard_runs.append(str(app.id))

        updated.append(app)
        if len(updated) >= BATCH_SIZE:
            OAuthApplication.objects.using(db_alias).bulk_update(updated, ["_provisioning_config"])
            updated = []
    if updated:
        OAuthApplication.objects.using(db_alias).bulk_update(updated, ["_provisioning_config"])

    # An active partner that loses wizard runs here is the intended outcome, but it is a
    # capability being taken away from a live integration, so name the rows in the deploy log
    # rather than letting them find out by 403.
    if lost_wizard_runs:
        logger.warning("provisioning_partners_lost_wizard_runs", application_ids=lost_wizard_runs)


class Migration(migrations.Migration):
    """Backfill provisioning_config from the per-capability columns.

    Alone in its own migration: a RunPython sharing a file with schema changes holds locks for
    the whole file. It has to run while those columns are still in the model state, which is why
    it sits before 1276 rather than after.
    """

    dependencies = [("posthog", "1273_oauth_provisioning_config")]

    operations = [
        migrations.RunPython(backfill_provisioning_config, migrations.RunPython.noop, elidable=True),
    ]
