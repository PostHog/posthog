from collections.abc import Iterator
from typing import Any

from django.core.management.base import BaseCommand

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.integration.push import apns_integration_id

logger = structlog.get_logger(__name__)


@frozen
class ApnsRowChange:
    """What one APNs credential row needs, or why it was left alone."""

    team_id: int
    integration_id: str
    new_integration_id: str | None = None
    strips_config: bool = False
    strips_signing_key: bool = False
    blocked_by_existing_row: bool = False
    unreadable: bool = False

    @property
    def changes_anything(self) -> bool:
        return bool(self.new_integration_id) or self.strips_config or self.strips_signing_key


def apns_environment(integration: Integration) -> str | None:
    config = integration.config
    return config.get("environment") if isinstance(config, dict) else None


def sorted_apns_integrations() -> list[Integration]:
    # Sandbox rows move first. A production row that only needs whitespace stripped can be waiting
    # for the bare id a sandbox row still holds, and it would keep the whitespace if it were read
    # first.
    return sorted(
        Integration.objects.filter(kind="apns"),
        key=lambda integration: apns_environment(integration) != "sandbox",
    )


def normalize_one_apns_integration(
    integration: Integration, occupied: dict[tuple[int, str], int], *, dry_run: bool
) -> ApnsRowChange | None:
    config: dict[str, Any] = dict(integration.config or {})
    team_id_apple = config.get("team_id")
    bundle_id = config.get("bundle_id")
    key_id = config.get("key_id")

    # The create path took any truthy JSON value for these until now, so a stored value is not
    # always a string. A row holding a number or a list has no id to compute, so it keeps the row
    # it has and this names the team.
    if not isinstance(team_id_apple, str) or not isinstance(bundle_id, str):
        return ApnsRowChange(
            team_id=integration.team_id,
            integration_id=integration.integration_id,
            unreadable=True,
        )

    team_id_apple = team_id_apple.strip()
    bundle_id = bundle_id.strip()
    if isinstance(key_id, str):
        key_id = key_id.strip()
    if not team_id_apple or not bundle_id:
        return ApnsRowChange(
            team_id=integration.team_id,
            integration_id=integration.integration_id,
            unreadable=True,
        )

    update_fields = []

    # A leading space breaks ES256 signing outright, so a credential stored with one has never
    # been able to send. Trailing whitespace is tolerated by the signer but is stripped with it.
    #
    # `sensitive_config` sets `ignore_decrypt_errors`, so a row written under a key we no longer
    # hold reads back as the raw ciphertext string, not a dict. Such a row keeps the key it has:
    # the value is unreadable, it carries no whitespace to strip, and saving it would add a
    # second layer of encryption over the first.
    stored_sensitive_config = integration.sensitive_config
    signing_key = stored_sensitive_config.get("signing_key") if isinstance(stored_sensitive_config, dict) else None
    strips_signing_key = isinstance(signing_key, str) and signing_key != signing_key.strip()
    if strips_signing_key:
        integration.sensitive_config = {**stored_sensitive_config, "signing_key": signing_key.strip()}
        update_fields.append("sensitive_config")

    strips_config = (config.get("team_id"), config.get("bundle_id"), config.get("key_id")) != (
        team_id_apple,
        bundle_id,
        key_id,
    )
    if strips_config:
        config.update({"team_id": team_id_apple, "bundle_id": bundle_id, "key_id": key_id})
        integration.config = config
        update_fields.append("config")

    wanted_id = apns_integration_id(team_id_apple, bundle_id, config.get("environment") or "")
    # `occupied` tracks the ids this run has already moved, so a dry run reports the same result as
    # a real one. Reading the database instead would still see a row at the id a sandbox row is
    # about to give up, and call the production row blocked.
    holder = occupied.get((integration.team_id, wanted_id))
    taken = holder is not None and holder != integration.pk
    new_integration_id = None
    if integration.integration_id != wanted_id and not taken:
        new_integration_id = wanted_id
        occupied.pop((integration.team_id, integration.integration_id), None)
        occupied[(integration.team_id, wanted_id)] = integration.pk
        integration.integration_id = wanted_id
        update_fields.append("integration_id")

    change = ApnsRowChange(
        team_id=integration.team_id,
        integration_id=integration.integration_id if new_integration_id is None else wanted_id,
        new_integration_id=new_integration_id,
        strips_config=strips_config,
        strips_signing_key=strips_signing_key,
        # Two rows of one environment whose ids differ only by whitespace. Deleting either one
        # drops a credential a team may still send with, so both stay and this names the team.
        blocked_by_existing_row=taken and integration.integration_id != wanted_id,
    )
    if not update_fields:
        return change if change.blocked_by_existing_row else None

    if not dry_run:
        integration.save(update_fields=update_fields)
    return change


def normalize_apns_integrations(*, dry_run: bool = False) -> Iterator[ApnsRowChange]:
    """Give each sandbox APNs credential its own row identity, and drop copied whitespace.

    The identity used to be the Apple team id and bundle id alone, so connecting a sandbox
    credential overwrote the production one for the same app. Sandbox rows move to the suffixed id
    the code now writes, which frees the bare id for the production credential.
    """
    integrations = sorted_apns_integrations()
    occupied = {(integration.team_id, integration.integration_id): integration.pk for integration in integrations}

    for integration in integrations:
        # `config` and `sensitive_config` are JSON columns that held whatever the create path was
        # given, so a row can hold a shape this code does not expect. One such row must not stop
        # the run.
        try:
            change = normalize_one_apns_integration(integration, occupied, dry_run=dry_run)
        except Exception:
            logger.warning(
                "apns_integration_not_normalized",
                team_id=integration.team_id,
                integration_id=integration.integration_id,
                exc_info=True,
            )
            yield ApnsRowChange(
                team_id=integration.team_id,
                integration_id=integration.integration_id,
                unreadable=True,
            )
            continue
        if change is not None:
            yield change


class Command(BaseCommand):
    help = "Move APNs sandbox credentials to their own row identity and strip stored whitespace"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report what would change and write nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: nothing is written."))

        counts = {"reidentified": 0, "stripped": 0, "blocked": 0, "unreadable": 0}
        for change in normalize_apns_integrations(dry_run=dry_run):
            if change.unreadable:
                counts["unreadable"] += 1
                self.stdout.write(f"team {change.team_id}: cannot read {change.integration_id}, left alone")
                continue
            if change.blocked_by_existing_row:
                counts["blocked"] += 1
                self.stdout.write(
                    self.style.WARNING(f"team {change.team_id}: {change.integration_id} is taken, left alone")
                )
            if change.new_integration_id:
                counts["reidentified"] += 1
                self.stdout.write(f"team {change.team_id}: id becomes {change.new_integration_id}")
            if change.strips_config or change.strips_signing_key:
                counts["stripped"] += 1
                stripped = ", ".join(
                    name
                    for name, changed in (("config", change.strips_config), ("signing key", change.strips_signing_key))
                    if changed
                )
                self.stdout.write(f"team {change.team_id}: whitespace stripped from {stripped}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {counts['reidentified']} reidentified, {counts['stripped']} stripped, "
                f"{counts['blocked']} blocked, {counts['unreadable']} unreadable."
            )
        )
