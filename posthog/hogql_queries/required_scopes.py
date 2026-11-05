from pydantic import BaseModel, ValidationError

from posthog.hogql_queries.access_controlled_resources import queried_access_controlled_resources
from posthog.models.team import Team

QUERY_RESOURCE_SCOPE_LABEL_PREFIX = "required_scope:"


def required_query_resource_scopes(query: BaseModel, team: Team) -> list[str]:
    while isinstance(query, BaseModel):
        if getattr(query, "kind", None) == "InboxUsageQuery":
            return ["signal_usage:read"]
        if getattr(query, "kind", None) == "HogQLQuery":
            resources = queried_access_controlled_resources(query, team)
            # A saved view can hide the table name; unresolved dependencies must not bypass its scope.
            return ["signal_usage:read"] if resources is None or "signal_usage" in resources else []
        source = getattr(query, "source", None)
        if not isinstance(source, BaseModel):
            break
        query = source
    return []


def query_resource_scope_labels_for_payload(query_json: dict, team: Team) -> list[str]:
    from posthog.schema import QuerySchemaRoot

    from posthog.schema_migrations.upgrade import upgrade

    try:
        query = QuerySchemaRoot.model_validate(upgrade(query_json)).root
    except ValidationError:
        # process_query_dict translates invalid payloads into the client-facing schema error.
        return []
    return [f"{QUERY_RESOURCE_SCOPE_LABEL_PREFIX}{scope}" for scope in required_query_resource_scopes(query, team)]
