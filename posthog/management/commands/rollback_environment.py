"""
Synchronously roll back an organization's environments by collapsing source
teams into target teams within the same project.

Restored as a standalone, self-contained command after the original
environments rollback feature (Celery task + Redis-backed dedupe + admin UI)
was removed in PR #46392. This version intentionally:

- Runs inline (no Celery dispatch), suitable for small organizations.
- Does not write to Redis; reruns are not blocked, so use --dry-run first.
- Does not emit any analytics events or in-product notifications.
- Does not send any email to organization members.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, models, transaction

from posthog.models import (
    Annotation,
    Cohort,
    EventDefinition,
    GroupTypeMapping,
    Organization,
    Project,
    PropertyDefinition,
    Team,
)
from posthog.models.group_type_mapping import invalidate_group_types_cache
from posthog.person_db_router import PERSONS_DB_FOR_WRITE

from products.actions.backend.models.action import Action
from products.dashboards.backend.models.dashboard import Dashboard
from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.models.insight import Insight
from products.surveys.backend.models import Survey

MIGRATED_MODELS: tuple[type[models.Model], ...] = (
    Insight,
    Dashboard,
    FeatureFlag,
    Action,
    Survey,
    Experiment,
    Cohort,
    Annotation,
    EarlyAccessFeature,
    Notebook,
)


class Command(BaseCommand):
    help = "Roll back organization environments using source:target team mappings (sync, no notifications)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org-id",
            type=str,
            required=True,
            help="Organization UUID to roll back environments for",
        )
        parser.add_argument(
            "--team-mappings",
            type=str,
            required=True,
            help="Comma-separated list of source:target team ID pairs (e.g. '123:456,789:456,101:102')",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without executing the rollback",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip the interactive confirmation prompt",
        )

    def handle(self, *args, **options) -> None:
        org_id: str = options["org_id"]
        raw_mappings: str = options["team_mappings"]
        dry_run: bool = options["dry_run"]
        force: bool = options["force"]

        try:
            environment_mappings = self._parse_team_mappings(raw_mappings)
            organization = self._get_organization(org_id)

            self._display_plan(organization, environment_mappings)

            if dry_run:
                self.stdout.write(self.style.SUCCESS("DRY RUN: no changes made."))
                return

            if not force and not self._confirm():
                self.stdout.write("Rollback cancelled.")
                return

            self.stdout.write("Executing rollback...")
            _run_environments_rollback(
                organization_id=organization.id,
                environment_mappings=environment_mappings,
            )
            self.stdout.write(self.style.SUCCESS(f"Rollback completed for organization {organization.name}"))

        except Exception as e:
            raise CommandError(f"Rollback failed: {e}")

    def _parse_team_mappings(self, raw: str) -> dict[str, int]:
        mappings: dict[str, int] = {}
        for piece in raw.split(","):
            piece = piece.strip()
            if not piece:
                continue
            if ":" not in piece:
                raise CommandError(f"Invalid mapping format: '{piece}'. Use 'source:target'")
            source, target = piece.split(":", 1)
            source_id = int(source.strip())
            target_id = int(target.strip())
            if source_id == target_id:
                raise CommandError(f"Source and target cannot be the same: {source_id}")
            mappings[str(source_id)] = target_id

        if not mappings:
            raise CommandError("No valid team mappings provided")
        return mappings

    def _get_organization(self, org_id: str) -> Organization:
        try:
            return Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            raise CommandError(f"Organization {org_id} not found")

    def _display_plan(self, organization: Organization, mappings: dict[str, int]) -> None:
        self.stdout.write(f"\nOrganization: {organization.name} ({organization.id})")
        self.stdout.write(f"\nTeam mappings ({len(mappings)} pairs):")
        for source_id, target_id in mappings.items():
            self.stdout.write(f"  Team {source_id} -> Team {target_id}")

    def _confirm(self) -> bool:
        self.stdout.write(self.style.WARNING("\nWARNING: this operation cannot be undone."))
        try:
            response = input("Type 'ROLLBACK' to confirm: ")
        except KeyboardInterrupt:
            return False
        return response.strip() == "ROLLBACK"


def _run_environments_rollback(organization_id: int, environment_mappings: dict[str, int]) -> None:
    organization = Organization.objects.get(id=organization_id)

    all_environment_ids = set(map(int, environment_mappings.keys())) | set(environment_mappings.values())
    teams = list(Team.objects.filter(id__in=all_environment_ids, organization_id=organization.id))
    teams_by_id: dict[int, Team] = {team.id: team for team in teams}

    missing = all_environment_ids - set(teams_by_id)
    if missing:
        raise ValueError(f"Environments not found in organization {organization.id}: {sorted(missing)}")

    # Final names: "project_name (team_name)" unless they're already identical.
    team_naming_map: dict[int, str] = {}
    for team in teams:
        original_project_name = team.project.name
        if team.name == original_project_name:
            team_naming_map[team.id] = team.name
        else:
            team_naming_map[team.id] = f"{original_project_name} ({team.name})"

    for source_id_str, target_id in environment_mappings.items():
        source_id = int(source_id_str)
        if source_id == target_id:
            continue
        source_team = teams_by_id[source_id]
        target_team = teams_by_id[target_id]
        if source_team.project_id != target_team.project_id:
            raise ValueError(
                f"Cannot migrate between different projects: "
                f"source environment {source_id} (project {source_team.project_id}) "
                f"to target environment {target_id} (project {target_team.project_id})"
            )

    with transaction.atomic():
        for source_id_str, target_id in environment_mappings.items():
            source_id = int(source_id_str)
            if source_id == target_id:
                continue

            for model in MIGRATED_MODELS:
                model.objects.filter(team_id=source_id).update(team_id=target_id)  # type: ignore[attr-defined]

            source_team = teams_by_id[source_id]
            target_team = teams_by_id[target_id]
            original_project_name = source_team.project.name

            # When the source team IS the project's main team, the source's project
            # row must stay; move the *target* into a fresh project instead.
            if source_team.id == source_team.project.id:
                team_to_move = target_team
                environment_name = target_team.name
            else:
                team_to_move = source_team
                environment_name = source_team.name

            new_project_name = f"{original_project_name} - {environment_name}"

            try:
                new_project = Project.objects.create(
                    id=team_to_move.id,
                    name=new_project_name,
                    organization=organization,
                )
            except IntegrityError:
                raise IntegrityError(f"Project ID {team_to_move.id} already exists; cannot create new project.")

            team_to_move.project = new_project
            team_to_move.save()

        for team in teams:
            team.refresh_from_db()
            new_name = team_naming_map[team.id]
            team.project.name = new_name
            team.project.save()
            team.name = new_name
            team.save()

            EventDefinition.objects.filter(team_id=team.id).update(project_id=team.project_id)
            PropertyDefinition.objects.filter(team_id=team.id).update(project_id=team.project_id)
            # GroupTypeMapping lives in the persons DB on cloud deployments; route the write
            # explicitly so the update lands on the right database (otherwise it silently
            # no-ops where persons_db_writer is configured).
            GroupTypeMapping.objects.using(PERSONS_DB_FOR_WRITE).filter(  # nosemgrep: no-direct-persons-db-orm
                team_id=team.id
            ).update(project_id=team.project_id)
            invalidate_group_types_cache(team.project_id)
