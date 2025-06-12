import json
from structlog import get_logger

logger = get_logger(__name__)


def environments_rollback_migration(organization_id: int, environment_mappings: dict[str, int], user_id: int) -> None:
    """
    Migrates resources from multiple environments to a single environment.
    The source and target environments must be in the same project.
    """
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
    )
    from posthog.event_usage import groups
    from django.db import transaction
    import posthoganalytics

    try:
        organization = Organization.objects.get(id=organization_id)
        user = User.objects.get(id=user_id)
        membership = user.organization_memberships.get(organization=organization)

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
                if source_team.id != source_team.project_id:
                    new_project = Project.objects.create(
                        id=source_team.id, name=source_team.name, organization=organization
                    )
                    source_team.project = new_project
                    source_team.save()

            posthoganalytics.capture(
                str(user.distinct_id),
                "organization environments rollback completed",
                properties={
                    "environment_mappings": json.dumps(environment_mappings),
                    "organization_id": str(organization.id),
                    "organization_name": organization.name,
                    "user_role": membership.level,
                },
                groups=groups(organization),
            )

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
