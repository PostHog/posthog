from dataclasses import dataclass


@dataclass
class GraphQLResource:
    name: str  # the name of the resource in the graphql API
    query: str  # a paginated query for retrieving the graphql resource
    permissions_query: str | None = (
        None  # a query for validating permissions are appropriaetly set for acting on the resource
    )
