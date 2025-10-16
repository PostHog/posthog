from typing import Any

GraphQLResponse = dict[str, Any]


class GraphQLResource:
    def __init__(self, name: str, query: str, permissions_query: str | None = None, accessor: str | None = None):
        self.name: str = name
        self.query: str = query
        self.permissions_query: str | None = permissions_query
        # accessor is the dot separated path to follow to get to the PARENT of the nodes iterable returned
        # from a graphql response.
        self.accessor: str = accessor or f"data.{self.name}"

    def unwrap(self, payload: Any, accessor: str | None = None) -> Any:
        """Drill down into a graphql response payload with intentionally unsafe key lookup."""
        if accessor is None:
            accessor = self.accessor
        keys = accessor.split(".")
        ref = payload
        for key in keys:
            ref = ref[key]
        return ref

    def safe_unwrap(self, payload: Any, accessor: str | None = None) -> tuple[Any, bool]:
        """Drill down into a graphql response payload with safe key lookup.

        Returns data from within the payload and a boolean indicating whether the lookup succeeded.
        If not, the unmodified payload is returned
        """
        if accessor is None:
            accessor = self.accessor
        keys = accessor.split(".")
        ref = payload
        for key in keys:
            ref = ref.get(key, None)
            if ref is None:
                return payload, False
        return ref, True
