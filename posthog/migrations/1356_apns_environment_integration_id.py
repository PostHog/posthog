from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def normalize_apns_integrations(apps, schema_editor):
    """Give each sandbox APNs credential its own row identity, and drop copied whitespace.

    The identity used to be the Apple team id and bundle id alone, so connecting a sandbox
    credential overwrote the production one for the same app. Sandbox rows move to the suffixed
    id the code now writes, which frees the bare id for the production credential.

    Whitespace is stripped in the same pass: a space copied out of the developer portal corrupts
    the signed JWT and the apns-topic, and it is invisible wherever the value is shown back.
    """
    Integration = apps.get_model("posthog", "Integration")

    # Sandbox rows move first. A production row that only needs whitespace stripped can be waiting for
    # the bare id a sandbox row still holds, and it would keep the whitespace if it were read first.
    integrations = sorted(
        Integration.objects.filter(kind="apns"),
        key=lambda integration: (integration.config or {}).get("environment") != "sandbox",
    )

    for integration in integrations:
        config = dict(integration.config or {})
        team_id_apple = config.get("team_id")
        bundle_id = config.get("bundle_id")
        key_id = config.get("key_id")

        # The create path took any truthy JSON value for these until now, so a stored value is not
        # always a string. A row holding a number or a list has no id to compute, and raising on it
        # would abort the whole migration, so it keeps the row it has and this names the team.
        if not isinstance(team_id_apple, str) or not isinstance(bundle_id, str):
            logger.warning(
                "apns_integration_config_not_a_string",
                team_id=integration.team_id,
                integration_id=integration.integration_id,
            )
            continue

        team_id_apple = team_id_apple.strip()
        bundle_id = bundle_id.strip()
        if isinstance(key_id, str):
            key_id = key_id.strip()
        if not team_id_apple or not bundle_id:
            continue

        update_fields = []

        # A leading space breaks ES256 signing outright, so a credential stored with one has never
        # been able to send. Trailing whitespace is tolerated by the signer but is stripped with it.
        sensitive_config = dict(integration.sensitive_config or {})
        signing_key = sensitive_config.get("signing_key")
        if isinstance(signing_key, str) and signing_key != signing_key.strip():
            sensitive_config["signing_key"] = signing_key.strip()
            integration.sensitive_config = sensitive_config
            update_fields.append("sensitive_config")

        if (config.get("team_id"), config.get("bundle_id"), config.get("key_id")) != (
            team_id_apple,
            bundle_id,
            key_id,
        ):
            config.update({"team_id": team_id_apple, "bundle_id": bundle_id, "key_id": key_id})
            integration.config = config
            update_fields.append("config")

        base = f"{team_id_apple}.{bundle_id}"
        integration_id = f"{base}:sandbox" if config.get("environment") == "sandbox" else base
        taken = (
            Integration.objects.filter(team_id=integration.team_id, kind="apns", integration_id=integration_id)
            .exclude(pk=integration.pk)
            .exists()
        )
        if integration.integration_id != integration_id and not taken:
            integration.integration_id = integration_id
            update_fields.append("integration_id")
        elif taken:
            # Two rows of one environment whose ids differ only by whitespace. Deleting either one
            # drops a credential a team may still send with, so both stay and this names the team.
            logger.warning(
                "apns_integration_id_taken",
                team_id=integration.team_id,
                integration_id=integration.integration_id,
            )

        if update_fields:
            integration.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [("posthog", "1355_datadeletionrequest_ddr_team_created_at_idx")]

    operations = [
        # Reverse is a no-op: the code this rolls back to reads the credential by team and bundle id,
        # which this does not change, and restoring the bare id would reintroduce the collision
        # between a sandbox row and a production one.
        migrations.RunPython(normalize_apns_integrations, migrations.RunPython.noop),
    ]
