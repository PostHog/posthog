import json
from dataclasses import dataclass
from structlog import get_logger
import posthoganalytics
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

logger = get_logger(__name__)


@dataclass
class RollbackEventContext:
    user: User
    organization: Organization
    membership: OrganizationMembership
    environment_mappings: dict[str, int]


def _capture_environments_rollback_event(
    event_name: str, context: RollbackEventContext, additional_properties: dict | None = None
) -> None:
    properties = {
        "environment_mappings": json.dumps(context.environment_mappings),
        "organization_id": str(context.organization.id),
        "organization_name": context.organization.name,
        "user_role": context.membership.level,
    }

    if additional_properties:
        properties.update(additional_properties)

    posthoganalytics.capture(
        str(context.user.distinct_id),
        event_name,
        properties=properties,
        groups=groups(context.organization),
    )


def environments_rollback_migration(organization_id: int, environment_mappings: dict[str, int], user_id: int) -> None:
    """
    Migrates resources from multiple environments to a single environment.
    The source and target environments must be in the same project.
    """
    try:
        organization = Organization.objects.get(id=organization_id)
        user = User.objects.get(id=user_id)
        membership = user.organization_memberships.get(organization=organization)
        context = RollbackEventContext(
            user=user, organization=organization, membership=membership, environment_mappings=environment_mappings
        )

        # Get all teams for this organization
        all_environment_ids = set(map(int, environment_mappings.keys())) | set(environment_mappings.values())
        teams = Team.objects.filter(id__in=all_environment_ids, organization_id=organization.id)

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

                # Create a new project for the source team
                source_team = teams.get(id=source_id)
                original_project_name = source_team.project.name
                environment_name = source_team.name
                new_project_name = f"{original_project_name} - {environment_name}"

                try:
                    new_project = Project.objects.create(
                        id=source_team.id, name=new_project_name, organization=organization
                    )
                except IntegrityError:
                    _capture_environments_rollback_event(
                        "organization environments rollback project id conflict",
                        context,
                        {
                            "conflicting_project_id": source_team.id,
                            "source_team_name": source_team.name,
                        },
                    )
                    raise IntegrityError(f"Project ID {source_team.id} already exists, cannot create new project.")

                source_team.project = new_project
                source_team.save()

        _capture_environments_rollback_event("organization environments rollback completed", context)

        logger.info(
            "Environments rollback migration completed successfully",
            organization_id=organization_id,
            environment_mappings=environment_mappings,
        )

    except Exception as e:
        logger.exception(
            "Environments rollback migration failed",
            organization_id=organization_id,
            environment_mappings=environment_mappings,
            error=str(e),
        )

        raise
