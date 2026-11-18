"""MotherDuck integration."""

from posthog.integrations.contracts import IntegrationConflict, IntegrationRecord
from posthog.models.user import User

from . import model, row_writes


class MotherDuckIntegrationError(Exception):
    """Error raised when a MotherDuck integration is not valid."""


class MotherDuckIntegration:
    """A MotherDuck integration storing a reusable MotherDuck access token.

    The database and schema stay on the destination config, so one token can serve many
    destinations. Like Snowflake, the row is keyed by a name the user chooses rather than by
    anything derived from the token, which allows several tokens per account for rotation.
    """

    integration: model.Integration

    def __init__(self, integration: IntegrationRecord) -> None:
        if integration.kind != model.Integration.IntegrationKind.MOTHERDUCK:
            raise MotherDuckIntegrationError(
                f"Integration provided is not a MotherDuck integration (got kind='{integration.kind}')"
            )
        self.integration = model.integration_model(integration)

    @property
    def access_token(self) -> str | None:
        return self.integration.sensitive_config.get("access_token")

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        name: object,
        access_token: object,
        created_by: User | None = None,
    ) -> IntegrationRecord:
        if not isinstance(name, str) or not isinstance(access_token, str):
            raise MotherDuckIntegrationError("Name and access token must be strings")
        name = name.strip()
        access_token = access_token.strip()
        if not name or not access_token:
            raise MotherDuckIntegrationError("Name and access token must be provided")

        # Create rather than upsert: reusing a name is a 400, not a silent overwrite of a token
        # that other destinations still use.
        try:
            return row_writes.creator_accessor(model.Integration.IntegrationKind.MOTHERDUCK.value).create(
                team_id,
                external_id=name,
                config={"name": name},
                sensitive_config={"access_token": access_token},
                created_by_id=created_by.id if created_by else None,
            )
        except IntegrationConflict:
            raise MotherDuckIntegrationError(f"An integration named '{name}' already exists")
