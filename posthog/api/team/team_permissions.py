"""Permissions for project settings routes."""

from rest_framework import exceptions, request
from rest_framework.permissions import BasePermission

from posthog.permissions import CREATE_ACTIONS


class PremiumMultiEnvironmentPermission(BasePermission):
    """Enforce one non-demo team per project limit."""

    message = "You have reached the maximum limit of allowed environments for your current plan. Upgrade your plan to be able to create and manage more environments."

    def has_permission(self, request: request.Request, view) -> bool:
        if view.action not in CREATE_ACTIONS:
            return True

        try:
            project = view.project
        except KeyError:  # KeyError occurs when "project_id" is not in parents_query_dict
            raise exceptions.ValidationError(
                "Environments must be created under a specific project. Send the POST request to /api/projects/<project_id>/environments/ instead."
            )

        if request.data.get("is_demo"):
            # Allow one demo team per organization
            if project.organization.teams.filter(is_demo=True).exists():
                return False
            return True

        # Only allow one non-demo team per project
        current_non_demo_team_count = project.teams.exclude(is_demo=True).count()
        if current_non_demo_team_count >= 1:
            return False

        return True
