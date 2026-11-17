import re
import uuid
from argparse import ArgumentParser
from collections import Counter
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from posthog.models.organization import Organization
from posthog.models.organization_provisioning import OrganizationProvisioning, mark_partner_paid


class Outcome(StrEnum):
    MARK = "mark"
    ALREADY_MARKED = "already marked"
    NO_PROVISIONING_ROW = "no provisioning row"
    PARTNER_DOES_NOT_PAY = "partner does not pay"
    NOT_FOUND = "not found"
    INVALID_ID = "invalid id"


def parse_organization_ids(tokens: Iterable[str], outcomes: Counter[Outcome]) -> set[uuid.UUID]:
    organization_ids: set[uuid.UUID] = set()
    for token in tokens:
        try:
            organization_ids.add(uuid.UUID(token))
        except ValueError:
            outcomes[Outcome.INVALID_ID] += 1
    return organization_ids


def classify(organization_exists: bool, provisioning: OrganizationProvisioning | None) -> Outcome:
    if not organization_exists:
        return Outcome.NOT_FOUND
    if provisioning is None:
        return Outcome.NO_PROVISIONING_ROW
    if provisioning.application is None or not provisioning.application.provisioning.pays_for_customers:
        return Outcome.PARTNER_DOES_NOT_PAY
    if provisioning.partner_paid_since is not None:
        return Outcome.ALREADY_MARKED
    return Outcome.MARK


def mark_partner_paid_organizations(tokens: Iterable[str], *, apply: bool) -> Counter[Outcome]:
    outcomes: Counter[Outcome] = Counter()
    organization_ids = parse_organization_ids(tokens, outcomes)
    existing_ids = set(Organization.objects.filter(id__in=organization_ids).values_list("id", flat=True))
    provisioning_rows = OrganizationProvisioning.objects.select_related("application").in_bulk(organization_ids)

    to_mark: list[uuid.UUID] = []
    for organization_id in organization_ids:
        outcome = classify(organization_id in existing_ids, provisioning_rows.get(organization_id))
        if outcome is Outcome.MARK:
            to_mark.append(organization_id)
        else:
            outcomes[outcome] += 1

    marked = len(to_mark)
    if apply and to_mark:
        # Billing sync can mark an organization after the read above, so count what this write marked.
        marked = mark_partner_paid(to_mark)
    outcomes[Outcome.MARK] += marked
    outcomes[Outcome.ALREADY_MARKED] += len(to_mark) - marked
    return outcomes


class Command(BaseCommand):
    help = (
        "Mark organizations as paid for by their provisioning partner, so the partner's billing lock stays on "
        "once billing syncs the Stripe customer it created for the partner's subscription. Takes organization "
        "ids from arguments and from --file, separated by whitespace or commas. Marks only organizations whose "
        "provisioning row names an application that pays for its customers, and never changes a marked one. "
        "Runs dry unless --apply is passed."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("organization_ids", nargs="*", help="Organization ids to mark.")
        parser.add_argument("--file", type=Path, help="A file of organization ids to mark.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without it the command only reports what it would do.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply: bool = options["apply"]
        text = " ".join(options["organization_ids"])
        if options["file"] is not None:
            text += " " + options["file"].read_text(encoding="utf-8-sig")
        tokens = [token for token in re.split(r"[\s,]+", text) if token]

        outcomes = mark_partner_paid_organizations(tokens, apply=apply)

        self.stdout.write("Applied." if apply else "Dry run, nothing written. Pass --apply to write.")
        for outcome in Outcome:
            label = str(outcome)
            if outcome is Outcome.MARK:
                label = "marked" if apply else "would mark"
            self.stdout.write(f"{label}: {outcomes[outcome]}")
