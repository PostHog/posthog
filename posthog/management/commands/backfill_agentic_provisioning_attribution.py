import csv
import uuid
from argparse import ArgumentParser
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Min

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import Change, Detail, Trigger, log_activity
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig

REQUIRED_COLUMNS = {"team_id", "partner_id"}
FIRST_TEAM_CREATION_WINDOW = timedelta(minutes=5)


class Outcome(StrEnum):
    CREATE = "create"
    FILL = "fill"
    ALREADY_ATTRIBUTED = "already_attributed"
    SKIPPED_OTHER_APPLICATION = "skipped_other_application"
    SKIPPED_CONFLICTING_PARTNERS = "skipped_conflicting_partners"
    SKIPPED_TEAM_NOT_FOUND = "skipped_team_not_found"
    SKIPPED_APPLICATION_NOT_FOUND = "skipped_application_not_found"
    SKIPPED_NOT_PROVISIONING_PARTNER = "skipped_not_provisioning_partner"
    SKIPPED_INVALID_ROW = "skipped_invalid_row"


WRITE_OUTCOMES = {Outcome.CREATE, Outcome.FILL}


class OrganizationOutcome(StrEnum):
    CREATE = "create"
    ALREADY_RECORDED = "already_recorded"
    SKIPPED_OTHER_PARTNER = "skipped_other_partner"
    SKIPPED_NOT_FIRST_TEAM = "skipped_not_first_team"
    SKIPPED_FIRST_TEAM_OTHER_APPLICATION = "skipped_first_team_other_application"


Source = Organization.ProvisioningSource


@frozen
class _OrganizationClaim:
    organization_id: uuid.UUID
    source: Source
    application_id: uuid.UUID | None


def _parse_row(row: Mapping[str, str | None]) -> tuple[int, uuid.UUID] | None:
    try:
        return int(row["team_id"] or ""), uuid.UUID((row["partner_id"] or "").strip())
    except ValueError:
        return None


def _partner_by_team(rows: Iterable[Mapping[str, str | None]], outcomes: Counter[Outcome]) -> dict[int, uuid.UUID]:
    partners_by_team: defaultdict[int, set[uuid.UUID]] = defaultdict(set)
    for row in rows:
        parsed = _parse_row(row)
        if parsed is None:
            outcomes[Outcome.SKIPPED_INVALID_ROW] += 1
        else:
            team_id, partner_id = parsed
            partners_by_team[team_id].add(partner_id)

    pairs: dict[int, uuid.UUID] = {}
    for team_id, partner_ids in partners_by_team.items():
        if len(partner_ids) > 1:
            outcomes[Outcome.SKIPPED_CONFLICTING_PARTNERS] += 1
        else:
            pairs[team_id] = next(iter(partner_ids))
    return pairs


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


def _write(team_id: int, application: OAuthApplication, outcome: Outcome) -> Outcome:
    if outcome is Outcome.CREATE:
        _, created = TeamProvisioningConfig.objects.get_or_create(
            team_id=team_id, defaults={"application": application}
        )
        if created:
            return Outcome.CREATE
    if TeamProvisioningConfig.objects.filter(team_id=team_id, application__isnull=True).update(application=application):
        return Outcome.FILL
    current = TeamProvisioningConfig.objects.filter(team_id=team_id).values_list("application_id", flat=True).first()
    return Outcome.ALREADY_ATTRIBUTED if current == application.id else Outcome.SKIPPED_OTHER_APPLICATION


def backfill_partner_attribution(rows: Iterable[Mapping[str, str | None]], *, live_run: bool) -> Counter[Outcome]:
    outcomes: Counter[Outcome] = Counter()
    pairs = _partner_by_team(rows, outcomes)

    applications = OAuthApplication.objects.in_bulk(set(pairs.values()))
    existing_team_ids = set(Team.objects.filter(id__in=pairs).values_list("id", flat=True))
    attributed: dict[int, uuid.UUID | None] = dict(
        TeamProvisioningConfig.objects.filter(team_id__in=pairs).values_list("team_id", "application_id")
    )

    for team_id, partner_id in pairs.items():
        application = applications.get(partner_id)
        outcome = _classify(team_id, application, existing_team_ids, attributed)
        if live_run and application is not None and outcome in WRITE_OUTCOMES:
            outcome = _write(team_id, application, outcome)
        outcomes[outcome] += 1
    return outcomes


def _provisioning_partner_teams(rows: Iterable[Mapping[str, str | None]]) -> dict[int, uuid.UUID]:
    pairs = _partner_by_team(rows, Counter())
    partner_ids = set(
        OAuthApplication.objects.filter(id__in=set(pairs.values()), is_provisioning_partner=True).values_list(
            "id", flat=True
        )
    )
    return {team_id: partner_id for team_id, partner_id in pairs.items() if partner_id in partner_ids}


def _first_team_claims(
    partner_by_team: Mapping[int, uuid.UUID], outcomes: Counter[OrganizationOutcome]
) -> list[_OrganizationClaim]:
    team_organizations = dict(Team.objects.filter(id__in=partner_by_team).values_list("id", "organization_id"))
    lowest_team_ids = set(
        Team.objects.filter(organization_id__in=set(team_organizations.values()))
        .values("organization_id")
        .annotate(lowest_team_id=Min("id"))
        .values_list("lowest_team_id", flat=True)
    )
    first_team_ids = set(
        Team.objects.filter(
            id__in=lowest_team_ids,
            created_at__lte=F("organization__created_at") + FIRST_TEAM_CREATION_WINDOW,
        ).values_list("id", flat=True)
    )
    first_team_applications: dict[int, uuid.UUID] = dict(
        TeamProvisioningConfig.objects.filter(team_id__in=first_team_ids, application__isnull=False).values_list(
            "team_id", "application_id"
        )
    )
    claims = []
    for team_id, application_id in partner_by_team.items():
        if team_id not in team_organizations:
            continue
        if team_id not in first_team_ids:
            outcomes[OrganizationOutcome.SKIPPED_NOT_FIRST_TEAM] += 1
            continue
        if first_team_applications.get(team_id) not in (None, application_id):
            outcomes[OrganizationOutcome.SKIPPED_FIRST_TEAM_OTHER_APPLICATION] += 1
            continue
        claims.append(
            _OrganizationClaim(
                organization_id=team_organizations[team_id],
                source=Source.PROVISIONING_API,
                application_id=application_id,
            )
        )
    return claims


def _log_organization_attribution(claim: _OrganizationClaim) -> None:
    organization = Organization.objects.only("name").get(id=claim.organization_id)
    changes = [
        Change(type="Organization", action="created", field="provisioning_source", before=None, after=claim.source)
    ]
    if claim.application_id is not None:
        application = OAuthApplication.objects.only("id", "name").get(id=claim.application_id)
        changes.append(
            Change(
                type="Organization",
                action="created",
                field="provisioning_application",
                before=None,
                after={"id": str(application.id), "name": application.name},
            )
        )
    log_activity(
        organization_id=claim.organization_id,
        team_id=None,
        user=None,
        item_id=claim.organization_id,
        scope="Organization",
        activity="updated",
        was_impersonated=False,
        detail=Detail(
            name=organization.name,
            changes=changes,
            trigger=Trigger(
                job_type="management_command", job_id="backfill_agentic_provisioning_attribution", payload={}
            ),
        ),
    )


def _record(claim: _OrganizationClaim) -> OrganizationOutcome:
    if Organization.objects.filter(
        id=claim.organization_id, provisioning_source__isnull=True, provisioning_application__isnull=True
    ).update(provisioning_source=claim.source, provisioning_application_id=claim.application_id):
        _log_organization_attribution(claim)
        return OrganizationOutcome.CREATE
    current = (
        Organization.objects.filter(id=claim.organization_id)
        .values_list("provisioning_source", "provisioning_application_id")
        .first()
    )
    if current == (claim.source, claim.application_id):
        return OrganizationOutcome.ALREADY_RECORDED
    return OrganizationOutcome.SKIPPED_OTHER_PARTNER


def backfill_organization_provisioning(
    rows: Iterable[Mapping[str, str | None]], *, live_run: bool
) -> dict[Source, Counter[OrganizationOutcome]]:
    outcomes: dict[Source, Counter[OrganizationOutcome]] = {
        Source.PROVISIONING_API: Counter(),
    }
    claims = _first_team_claims(_provisioning_partner_teams(rows), outcomes[Source.PROVISIONING_API])
    organization_ids = {claim.organization_id for claim in claims}
    recorded = {
        organization_id: (source, application_id)
        for organization_id, source, application_id in Organization.objects.filter(
            id__in=organization_ids, provisioning_source__isnull=False
        ).values_list("id", "provisioning_source", "provisioning_application_id")
    }

    for claim in claims:
        existing = recorded.get(claim.organization_id)
        if live_run and existing is None:
            outcome = _record(claim)
        elif existing is None:
            outcome = OrganizationOutcome.CREATE
        elif existing == (claim.source, claim.application_id):
            outcome = OrganizationOutcome.ALREADY_RECORDED
        else:
            outcome = OrganizationOutcome.SKIPPED_OTHER_PARTNER
        outcomes[claim.source][outcome] += 1
    return outcomes


class Command(BaseCommand):
    help = (
        "Attribute partner-created teams to the provisioning partner that created them, from a CSV "
        "with team_id and partner_id (OAuthApplication id) columns. Creates a missing "
        "TeamProvisioningConfig row or fills a null application, and never replaces a different one. "
        "Also records the partner that created each organization: the CSV partner when the attributed "
        "team is the organization's first team and is not attributed to a different application. Never replaces an "
        "organization's recorded partner."
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
            rows = list(reader)

        outcomes = backfill_partner_attribution(rows, live_run=live_run)
        organization_outcomes = backfill_organization_provisioning(rows, live_run=live_run)

        self.stdout.write("Live run." if live_run else "Dry run, nothing written. Pass --live-run to write.")
        for outcome in Outcome:
            label = f"would {outcome}" if not live_run and outcome in WRITE_OUTCOMES else str(outcome)
            self.stdout.write(f"{label}: {outcomes[outcome]}")
        for source, source_outcomes in organization_outcomes.items():
            for organization_outcome in OrganizationOutcome:
                label = (
                    f"would {organization_outcome}"
                    if not live_run and organization_outcome is OrganizationOutcome.CREATE
                    else str(organization_outcome)
                )
                self.stdout.write(f"{source} organizations, {label}: {source_outcomes[organization_outcome]}")
