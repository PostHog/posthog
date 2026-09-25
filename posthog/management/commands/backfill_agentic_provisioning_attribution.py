import csv
import uuid
from argparse import ArgumentParser
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.models.oauth import OAuthApplication
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

REQUIRED_COLUMNS = {"team_id", "partner_id"}


class Outcome(StrEnum):
    CREATE = "create"
    FILL = "fill"
    ALREADY_ATTRIBUTED = "already_attributed"
    SKIPPED_OTHER_APPLICATION = "skipped_other_application"
    SKIPPED_TEAM_NOT_FOUND = "skipped_team_not_found"
    SKIPPED_APPLICATION_NOT_FOUND = "skipped_application_not_found"
    SKIPPED_NOT_PROVISIONING_PARTNER = "skipped_not_provisioning_partner"
    SKIPPED_INVALID_ROW = "skipped_invalid_row"


WRITE_OUTCOMES = {Outcome.CREATE, Outcome.FILL}


def _parse_row(row: Mapping[str, str | None]) -> tuple[int, uuid.UUID] | None:
    try:
        return int(row.get("team_id") or ""), uuid.UUID((row.get("partner_id") or "").strip())
    except ValueError:
        return None


def _classify(
    team_id: int,
    application: OAuthApplication | None,
    existing_team_ids: set[int],
    attributed: dict[int, uuid.UUID | None],
) -> Outcome:
    if application is None:
        return Outcome.SKIPPED_APPLICATION_NOT_FOUND
    if not application.is_provisioning_partner:
        return Outcome.SKIPPED_NOT_PROVISIONING_PARTNER
    if team_id not in existing_team_ids:
        return Outcome.SKIPPED_TEAM_NOT_FOUND
    if team_id not in attributed:
        return Outcome.CREATE
    if attributed[team_id] is None:
        return Outcome.FILL
    if attributed[team_id] == application.id:
        return Outcome.ALREADY_ATTRIBUTED
    return Outcome.SKIPPED_OTHER_APPLICATION


def backfill_partner_attribution(rows: Iterable[Mapping[str, str | None]], *, live_run: bool) -> Counter[Outcome]:
    outcomes: Counter[Outcome] = Counter()
    pairs: dict[tuple[int, uuid.UUID], None] = {}
    for row in rows:
        parsed = _parse_row(row)
        if parsed is None:
            outcomes[Outcome.SKIPPED_INVALID_ROW] += 1
        else:
            pairs[parsed] = None

    team_ids = {team_id for team_id, _ in pairs}
    applications = OAuthApplication.objects.in_bulk({partner_id for _, partner_id in pairs})
    existing_team_ids = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
    attributed: dict[int, uuid.UUID | None] = dict(
        TeamProvisioningConfig.objects.filter(team_id__in=team_ids).values_list("team_id", "application_id")
    )

    for team_id, partner_id in pairs:
        application = applications.get(partner_id)
        outcome = _classify(team_id, application, existing_team_ids, attributed)
        outcomes[outcome] += 1
        if application is None or outcome not in WRITE_OUTCOMES:
            continue
        attributed[team_id] = application.id
        if not live_run:
            continue
        if outcome is Outcome.CREATE:
            TeamProvisioningConfig.objects.get_or_create(team_id=team_id, defaults={"application": application})
        else:
            TeamProvisioningConfig.objects.filter(team_id=team_id, application__isnull=True).update(
                application=application
            )
    return outcomes


class Command(BaseCommand):
    help = (
        "Attribute partner-created teams to the provisioning partner that created them, from a CSV "
        "with team_id and partner_id (OAuthApplication id) columns. Creates a missing "
        "TeamProvisioningConfig row or fills a null application, and never replaces a different one."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("csv_file", type=Path)
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Write the changes. Without it the command only reports what it would do.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        live_run: bool = options["live_run"]
        csv_path: Path = options["csv_file"]
        with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            missing_columns = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing_columns:
                raise CommandError(f"CSV is missing column(s): {', '.join(sorted(missing_columns))}")
            outcomes = backfill_partner_attribution(reader, live_run=live_run)

        self.stdout.write("Live run." if live_run else "Dry run, nothing written. Pass --live-run to write.")
        for outcome in Outcome:
            label = f"would {outcome}" if not live_run and outcome in WRITE_OUTCOMES else str(outcome)
            self.stdout.write(f"{label}: {outcomes[outcome]}")
