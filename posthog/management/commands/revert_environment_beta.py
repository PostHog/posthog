import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.models import Organization, Project, Team


class Command(BaseCommand):
    help = "Revert environment beta by splitting out teams that belong to multiple projects"

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization_ids",
            type=str,
            help="Organization ID or comma-separated list of organization IDs to process",
        )

    def handle(self, *args, **options):
        organization_ids_input = options.get("organization_ids")
        if not organization_ids_input:
            self.stdout.write("No organization IDs provided. Exiting.")
            return

        organization_ids = [int(org_id.strip()) for org_id in organization_ids_input.split(",") if org_id.strip()]

        if not organization_ids:
            self.stdout.write("No valid organization IDs provided. Exiting.")
            return

        self.stdout.write(
            f"Processing {len(organization_ids)} organization(s): {', '.join(map(str, organization_ids))}"
        )

        for org_id in organization_ids:
            self.stdout.write(f"\nProcessing organization with ID: {org_id}")
            self.revert_environment_beta(org_id)

        self.stdout.write("\nAll organizations processed successfully.")

    def revert_environment_beta(self, organization_id: int):
        """
        Revert environment beta by ensuring each team belongs to exactly one project.

        For each project with multiple teams, create new projects for teams where team.id != project.id,
        and move those teams to the new projects.

        Args:
            organization_id: The ID of the organization to process
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Starting environment beta reversion for organization {organization_id}")

        try:
            # Get the organization
            organization = Organization.objects.get(id=organization_id)
            logger.info(f"Found organization: {organization.name}")

            # Get all projects for this organization
            projects = Project.objects.filter(organization_id=organization_id)
            logger.info(f"Found {projects.count()} projects for organization {organization.name}")

            # Process each project
            for project in projects:
                # Get all teams for this project
                teams = Team.objects.filter(project_id=project.id)
                team_count = teams.count()

                if team_count <= 1:
                    logger.info(f"Project {project.id} ({project.name}) has {team_count} team(s). No action needed.")
                    continue

                logger.info(f"Project {project.id} ({project.name}) has {team_count} teams. Processing...")

                # Process each team in the project
                for team in teams:
                    # Skip the team if its ID matches the project ID (this team stays with the current project)
                    if team.id == project.id:
                        logger.info(f"Team {team.id} ({team.name}) matches project ID. Keeping in current project.")
                        continue

                    # Create a new project for this team
                    new_project_id = team.id

                    with transaction.atomic():
                        does_project_with_same_id_exist = Project.objects.filter(id=new_project_id).exists()
                        if does_project_with_same_id_exist:
                            logger.warning(
                                f"Project with ID {new_project_id} already exists. "
                                f"Using default ID generation for new project."
                            )
                            new_project = Project.objects.create(organization=organization, name=f"{team.name} Project")
                        else:
                            # Create a new project with the team's ID
                            new_project = Project.objects.create(
                                id=new_project_id, organization=organization, name=f"{team.name} Project"
                            )

                    logger.info(
                        f"Created new project {new_project.id} ({new_project.name}) "
                        f"for team {team.id} ({team.name})"
                    )

                    # Update the team to point to the new project
                    old_project_id = team.project_id
                    team.project = new_project
                    team.save(update_fields=["project"])

                    logger.info(
                        f"Moved team {team.id} ({team.name}) from project {old_project_id} "
                        f"to project {new_project.id}"
                    )

                    # Stub for duplicating resources
                    # self.duplicate_resources(team, old_project_id, new_project.id)

            logger.info(f"Successfully completed environment beta reversion for organization {organization_id}")

        except Organization.DoesNotExist:
            logger.exception(f"Organization with ID {organization_id} does not exist")
        except Exception as e:
            logger.exception(f"Error during environment beta reversion: {str(e)}")
            raise

    # def duplicate_resources(self, team: Team, old_project_id: int, new_project_id: int):
    #     """
    #     Stub function to duplicate resources from the old project to the new project.

    #     Args:
    #         team: The team being moved
    #         old_project_id: The ID of the old project
    #         new_project_id: The ID of the new project
    #     """
    #     logger = logging.getLogger(__name__)
    #     logger.info(
    #         f"STUB: Would duplicate resources for team {team.id} from project {old_project_id} "
    #         f"to project {new_project_id}"
    #     )
    #     # This function will be implemented later
    #     pass
