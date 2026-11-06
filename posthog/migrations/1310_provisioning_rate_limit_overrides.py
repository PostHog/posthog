from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500

UNLIMITED_OVERRIDE = -1

TIER_SOURCES = ["default_verified", "default_unverified"]


def migrate_rate_limit_overrides(apps, schema_editor):
    """Clear the persisted CIMD tier values so the derived tier applies again.

    Rate limits used to mix two kinds of value in one place: admin overrides and the
    CIMD verified/unverified tier defaults (10/100), disambiguated by rate_limit_source.
    Tiers are now derived per request, so a persisted tier value would be read as an
    admin override and pin the partner to the old number forever. Only those rows are
    rewritten: rate_limit_source in (default_verified, default_unverified), dropping
    the account_requests value the tiering wrote. Other keys on those rows stay, since
    the source tracked account_requests alone.

    Everything else the old shape stored is left alone, because ProvisioningConfig
    already reads it correctly: the rate_limits validator drops nulls and maps 0 to
    UNLIMITED_OVERRIDE, and extra="ignore" ignores a leftover rate_limit_source. Those
    keys are dead weight rather than wrong, and rewriting them would mean touching
    every row in a table 1274 backfilled in full. They clear themselves the next time
    anything saves the config.
    """
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")

    # Pinned to the alias `migrate` is running on rather than letting the router pick;
    # see 1274 for why (server-side cursors on default_direct).
    db_alias = schema_editor.connection.alias

    # Filtered in Postgres, not in Python: 1274 backfilled a config onto all of the
    # table, so streaming it to find the tier-sourced rows would read millions to write
    # a handful.
    candidates = (
        OAuthApplication.objects.using(db_alias)
        .filter(_provisioning_config__rate_limit_source__in=TIER_SOURCES)
        .order_by("pk")
    )

    cleared_tier_values = []
    updated = []
    for app in candidates.iterator(chunk_size=BATCH_SIZE):
        config = app._provisioning_config or {}
        raw_limits = config.get("rate_limits") or {}

        limits = {}
        for key, value in raw_limits.items():
            if value is None:
                continue
            if key == "account_requests":
                cleared_tier_values.append(str(app.pk))
                continue
            limits[key] = UNLIMITED_OVERRIDE if value <= 0 else value

        new_config = {k: v for k, v in config.items() if k != "rate_limit_source"}
        new_config["rate_limits"] = limits

        app._provisioning_config = new_config
        updated.append(app)
        if len(updated) >= BATCH_SIZE:
            OAuthApplication.objects.using(db_alias).bulk_update(updated, ["_provisioning_config"])
            updated = []

    if updated:
        OAuthApplication.objects.using(db_alias).bulk_update(updated, ["_provisioning_config"])

    if cleared_tier_values:
        logger.info(
            "provisioning_tier_rate_limits_cleared",
            application_ids=cleared_tier_values,
            count=len(cleared_tier_values),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1309_integration_kind_ext_idx"),
    ]

    operations = [
        migrations.RunPython(migrate_rate_limit_overrides, migrations.RunPython.noop, elidable=True),
    ]
