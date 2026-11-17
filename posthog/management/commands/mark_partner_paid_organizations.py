import re
import uuid
from argparse import ArgumentParser
from collections import defaultdict
from collections.abc import Collection, Iterable
from enum import StrEnum
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.dataclasses import frozen
from posthog.models.organization import Organization
from posthog.models.organization_provisioning import OrganizationProvisioning, mark_partner_paid


class Outcome(StrEnum):
    MARKED = "marked"
    UNMARKED = "unmarked"
    ALREADY_MARKED = "already marked"
    NOT_MARKED = "not marked"
    PARTNER_DOES_NOT_PAY = "partner does not pay"
    NO_PROVISIONING_ROW = "no provisioning row"
    NOT_FOUND = "not found"
    INVALID_ID = "invalid id"
    CHANGED_DURING_RUN = "skipped, changed during run"


MARK_OUTCOMES = (
    Outcome.MARKED,
    Outcome.ALREADY_MARKED,
    Outcome.PARTNER_DOES_NOT_PAY,
    Outcome.NO_PROVISIONING_ROW,
    Outcome.NOT_FOUND,
    Outcome.INVALID_ID,
    Outcome.CHANGED_DURING_RUN,
)
UNMARK_OUTCOMES = (
    Outcome.UNMARKED,
    Outcome.NOT_MARKED,
    Outcome.NO_PROVISIONING_ROW,
    Outcome.NOT_FOUND,
    Outcome.INVALID_ID,
    Outcome.CHANGED_DURING_RUN,
)
DRY_RUN_LABELS = {Outcome.MARKED: "would mark", Outcome.UNMARKED: "would unmark"}


@frozen
class ProvisioningState:
    partner_pays: bool
    marked: bool


def parse_organization_ids(tokens: Iterable[str]) -> tuple[set[uuid.UUID], list[str]]:
    organization_ids: set[uuid.UUID] = set()
    invalid: list[str] = []
    for token in tokens:
        try:
            organization_ids.add(uuid.UUID(token))
        except ValueError:
            invalid.append(token)
    return organization_ids, invalid


def classify(*, unmark: bool, organization_exists: bool, provisioning: ProvisioningState | None) -> Outcome:
    if not organization_exists:
        return Outcome.NOT_FOUND
    if provisioning is None:
        return Outcome.NO_PROVISIONING_ROW
    if unmark:
        return Outcome.UNMARKED if provisioning.marked else Outcome.NOT_MARKED
    if not provisioning.partner_pays:
        return Outcome.PARTNER_DOES_NOT_PAY
    return Outcome.ALREADY_MARKED if provisioning.marked else Outcome.MARKED


def _provisioning_states(organization_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, ProvisioningState]:
    rows = OrganizationProvisioning.objects.filter(organization_id__in=organization_ids)
    paid_by_partner = set(rows.paid_by_partner().values_list("organization_id", flat=True))
    return {
        organization_id: ProvisioningState(
            partner_pays=organization_id in paid_by_partner, marked=marked_at is not None
        )
        for organization_id, marked_at in rows.values_list("organization_id", "partner_paid_since")
    }


def _write(organization_id: uuid.UUID, *, unmark: bool) -> bool:
    # One UPDATE per organization, so the report names each organization that changed between the read
    # and the write, for example one that billing sync marked meanwhile.
    if unmark:
        return bool(
            OrganizationProvisioning.objects.filter(
                organization_id=organization_id, partner_paid_since__isnull=False
            ).update(partner_paid_since=None)
        )
    return bool(mark_partner_paid([organization_id]))


def change_partner_paid_marks(tokens: Iterable[str], *, unmark: bool, apply: bool) -> dict[Outcome, list[str]]:
    organization_ids, invalid = parse_organization_ids(tokens)
    existing_ids = set(Organization.objects.filter(id__in=organization_ids).values_list("id", flat=True))
    states = _provisioning_states(organization_ids)

    outcomes: defaultdict[Outcome, list[str]] = defaultdict(list)
    outcomes[Outcome.INVALID_ID] = invalid
    for organization_id in sorted(organization_ids):
        outcome = classify(
            unmark=unmark,
            organization_exists=organization_id in existing_ids,
            provisioning=states.get(organization_id),
        )
        if apply and outcome in (Outcome.MARKED, Outcome.UNMARKED) and not _write(organization_id, unmark=unmark):
            outcome = Outcome.CHANGED_DURING_RUN
        outcomes[outcome].append(str(organization_id))
    return outcomes


class Command(BaseCommand):
    help = (
        "Mark organizations as paid for by their provisioning partner, so the partner's billing lock stays on "
        "once billing syncs the Stripe customer it created for the partner's subscription. With --unmark, clear "
        "the mark, for example after billing ends one organization's payer link. Takes organization ids from "
        "arguments and from --file, separated by whitespace or commas. Marks only organizations whose "
        "provisioning row names an application that pays for its customers. Prints the ids for each outcome. "
        "Runs dry unless --apply is passed."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("organization_ids", nargs="*", help="Organization ids to mark or unmark.")
        parser.add_argument("--file", type=Path, help="A file of organization ids to mark or unmark.")
        parser.add_argument("--unmark", action="store_true", help="Clear the mark instead of setting it.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without it the command only reports what it would do.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply: bool = options["apply"]
        unmark: bool = options["unmark"]
        text = " ".join(options["organization_ids"])
        if options["file"] is not None:
            text += " " + options["file"].read_text(encoding="utf-8-sig")
        tokens = [token for token in re.split(r"[\s,]+", text) if token]
        if not tokens:
            raise CommandError("Pass organization ids as arguments or with --file.")

        outcomes = change_partner_paid_marks(tokens, unmark=unmark, apply=apply)

        self.stdout.write("Applied." if apply else "Dry run, nothing written. Pass --apply to write.")
        for outcome in UNMARK_OUTCOMES if unmark else MARK_OUTCOMES:
            label = str(outcome) if apply else DRY_RUN_LABELS.get(outcome, str(outcome))
            ids = outcomes.get(outcome, [])
            self.stdout.write(f"{label}: {len(ids)}")
            if ids:
                self.stdout.write(f"  {', '.join(ids)}")
