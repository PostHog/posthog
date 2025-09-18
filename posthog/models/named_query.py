import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel


def validate_query_name(value: str) -> None:
    """Validate that the query name is URL-safe and follows naming conventions."""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", value):
        raise ValidationError(
            f"{value} is not a valid query name. Query names must start with a letter and contain only letters, numbers, hyphens, and underscores.",
            params={"value": value},
        )

    if len(value) > 128:
        raise ValidationError(
            f"Query name '{value}' is too long. Maximum length is 128 characters.",
            params={"value": value},
        )


class NamedQuery(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    """Model for storing named queries that can be accessed via API endpoints.

    Named queries allow creating reusable query endpoints like:
    /api/environments/{team_id}/named_query/{query_name}

    The query field follows the same structure as QueryRequest.query, supporting
    any query type accepted by the /query endpoint (HogQLQuery, TrendsQuery, etc.).
    """

    name = models.CharField(
        max_length=128, validators=[validate_query_name], help_text="URL-safe name for the query endpoint"
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE)

    # Use JSONField to store the query, following the same pattern as QueryRequest.query
    # This can store any of the query types: HogQLQuery, TrendsQuery, FunnelsQuery, etc.
    query = models.JSONField(help_text="Query definition following QueryRequest.query schema")

    description = models.TextField(blank=True, help_text="Human-readable description of what this query does")

    # Parameter schema for query customization
    parameters = models.JSONField(
        default=dict, blank=True, help_text="JSON schema defining expected parameters for query customization"
    )

    is_active = models.BooleanField(default=True, help_text="Whether this named query is available via the API")

    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_team_named_query_name",
            )
        ]
        indexes = [
            models.Index(fields=["team", "is_active"]),
            models.Index(fields=["team", "name"]),
        ]

    def __str__(self) -> str:
        return f"{self.team.name}: {self.name}"

    @property
    def endpoint_path(self) -> str:
        """Return the API endpoint path for this named query."""
        # return reverse("delete_named_query", {"team_id": self.team.id, "query_name": self.name})
        return f"/api/environments/{self.team.id}/named_query/d/{self.name}"

    def get_query_with_parameters(self, request_params: dict[str, Any]) -> dict[str, Any]:
        """Apply request parameters to the stored query.

        This method handles parameter injection for query customization.
        For now, it returns the query as-is, but can be extended to support
        parameter substitution in the future.
        """
        # TODO: Implement parameter substitution logic
        # For example, replacing {parameter_name} placeholders in HogQL queries
        return self.query

    def validate_parameters(self, request_params: dict[str, Any]) -> None:
        """Validate request parameters against the parameter schema.

        This method can be extended to implement JSON schema validation
        of incoming parameters.
        """
        # TODO: Implement parameter validation logic
        pass
