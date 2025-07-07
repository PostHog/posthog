# ruff: noqa: T201
import json
from dataclasses import dataclass
from posthog.ph_client import get_client
from posthoganalytics import Posthog
from posthog.event_usage import groups
from posthog.models import (
    User,
    Team,
    Project,
    Organization,
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
from posthog.models.organization import OrganizationMembership
from django.db import transaction, IntegrityError


@dataclass
class RollbackEventContext:
    user: User
    organization: Organization
    membership: OrganizationMembership
    environment_mappings: dict[str, int]


def _capture_environments_rollback_event(
    event_name: str, context: RollbackEventContext, posthog_client: Posthog, additional_properties: dict | None = None
) -> None:
    properties = {
        "environment_mappings": json.dumps(context.environment_mappings),
        "organization_id": str(context.organization.id),
        "organization_name": context.organization.name,
        "user_role": context.membership.level,
    }

    if additional_properties:
        properties.update(additional_properties)

    posthog_client.capture(
        distinct_id=str(context.user.distinct_id),
        event=event_name,
        properties=properties,
        groups=groups(context.organization),
    )
    posthog_client.flush()


def environments_rollback_migration(organization_id: int, environment_mappings: dict[str, int], user_id: int) -> None:
    """
    Migrates resources from multiple environments to a single environment.
    The source and target environments must be in the same project.
    """
    try:
        posthog_client = get_client()
        organization = Organization.objects.get(id=organization_id)
        user = User.objects.get(id=user_id)
        membership = user.organization_memberships.get(organization=organization)
        context = RollbackEventContext(
            user=user, organization=organization, membership=membership, environment_mappings=environment_mappings
        )

        # Get all teams for this organization
        all_environment_ids = set(map(int, environment_mappings.keys())) | set(environment_mappings.values())
        teams = Team.objects.filter(id__in=all_environment_ids, organization_id=organization.id)

        # Create naming mapping for all affected teams upfront
        team_naming_map = {}  # {team_id: "project_name (team_name)"}

        for team in teams:
            original_project_name = team.project.name
            if team.name == original_project_name:
                team_naming_map[team.id] = team.name
            else:
                team_naming_map[team.id] = f"{original_project_name} ({team.name})"

        # Verify each source-target pair belongs to the same project
        teams_by_id = {team.id: team for team in teams}
        for source_id_str, target_id in environment_mappings.items():
            source_id = int(source_id_str)
            if source_id == target_id:
                continue  # Skip self-mappings

            source_team = teams_by_id[source_id]
            target_team = teams_by_id[target_id]

            if source_team.project_id != target_team.project_id:
                raise ValueError(
                    f"Cannot migrate between different projects: "
                    f"source environment {source_id} (project {source_team.project_id}) "
                    f"to target environment {target_id} (project {target_team.project_id})"
                )

        models_to_update = [
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
        ]

        with transaction.atomic():
            # Update all models to point to their target teams
            for source_id_str, target_id in environment_mappings.items():
                source_id = int(source_id_str)

                if source_id == target_id:
                    continue  # Skip if source and target are the same

                # Update all models from source to target
                for model in models_to_update:
                    model.objects.filter(team_id=source_id).update(team_id=target_id)  # type: ignore[attr-defined]

                source_team = teams_by_id[source_id]
                target_team = teams_by_id[target_id]
                original_project_name = source_team.project.name

                # If source team ID equals project ID (main environment),
                # create new project for target team instead
                if source_team.id == source_team.project.id:
                    team_to_move = target_team
                    environment_name = target_team.name
                else:
                    team_to_move = source_team
                    environment_name = source_team.name

                new_project_name = f"{original_project_name} - {environment_name}"

                try:
                    new_project = Project.objects.create(
                        id=team_to_move.id, name=new_project_name, organization=organization
                    )
                except IntegrityError:
                    _capture_environments_rollback_event(
                        "organization environments rollback project id conflict",
                        context,
                        posthog_client,
                        {
                            "conflicting_project_id": team_to_move.id,
                            "team_name": team_to_move.name,
                        },
                    )
                    raise IntegrityError(f"Project ID {team_to_move.id} already exists, cannot create new project.")

                team_to_move.project = new_project
                team_to_move.save()

            # Apply naming to all affected teams
            for team in teams:
                team.refresh_from_db()
                new_name = team_naming_map[team.id]

                # Skip renaming if environment originally had same name as project
                team.project.name = new_name
                team.project.save()

                team.name = new_name
                team.save()

        _capture_environments_rollback_event("organization environments rollback completed", context, posthog_client)

        print(
            f"Environments rollback migration completed successfully - "
            f"organization_id={organization_id}, environment_mappings={environment_mappings}"
        )

    except Exception as e:
        print(
            f"Environments rollback migration failed - "
            f"organization_id={organization_id}, environment_mappings={environment_mappings}, error={str(e)}"
        )

        raise

    finally:
        posthog_client.shutdown()
