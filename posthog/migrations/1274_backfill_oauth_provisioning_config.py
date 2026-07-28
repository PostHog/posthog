from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def backfill_provisioning_config(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")

    # Only rows that carry provisioning state. Every other app keeps the empty-object default,
    # which reads back as a partner that may do nothing.
    candidates = OAuthApplication.objects.exclude(
        is_provisioning_partner=False,
        provisioning_partner_type="",
        provisioning_active=False,
    ).order_by("pk")

    updated = []
    for app in candidates.iterator(chunk_size=BATCH_SIZE):
        # provisioning_partner_type was doing double duty as the marker for a partner PostHog
        # vouched for, and it is the only signal available here for who keeps the two elevated
        # capabilities. A self-registered CIMD partner never had one set, so it does not get
        # them - which is the restriction this change exists to introduce.
        vouched_for = bool(app.provisioning_partner_type)

        app._provisioning_config = {
            "active": app.provisioning_active,
            "disabled": app.provisioning_disabled,
            "can_create_accounts": app.provisioning_can_create_accounts,
            "can_provision_resources": app.provisioning_can_provision_resources,
            # The old gate was `is_cimd_client and not provisioning_partner_type`, so a non-CIMD
            # partner passed on being admin-created alone. Both collapse to one capability, and
            # this mapping preserves exactly who can call the endpoints.
            "can_use_github_grants": vouched_for or not app.is_cimd_client,
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
        updated.append(app)
        if len(updated) >= BATCH_SIZE:
            OAuthApplication.objects.bulk_update(updated, ["_provisioning_config"])
            updated = []
    if updated:
        OAuthApplication.objects.bulk_update(updated, ["_provisioning_config"])

    # An active partner that loses wizard runs here is the intended outcome, but it is a
    # capability being taken away from a live integration, so name the rows in the deploy log
    # rather than letting them find out by 403.
    lost_wizard_runs = list(
        candidates.filter(
            provisioning_active=True,
            provisioning_can_provision_resources=True,
            provisioning_partner_type="",
        ).values_list("id", flat=True)
    )
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
