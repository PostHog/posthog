from abc import ABC, abstractmethod


class SchemaMigration(ABC):
    """
    Base class for schema migrations. Bumps the schema of one or more query types by one version.

    Subclasses must define:
    * `targets`: A mapping of node kinds to the version before running the migration.
    * `transform`: A method that takes a dict query and returns a new dict query with the updated schema version.
    """

    targets: dict[str, int] = {}

    def __call__(self, query: dict) -> dict:
        """Apply if version matches, otherwise return untouched."""
        if not self.should_run(query):
            return query
        query = self.transform(query)
        query["version"] = self.targets[query["kind"]] + 1  # bump version
        return query

    def should_run(self, query: dict) -> bool:
        kind = query.get("kind")
        return kind in self.targets and (query.get("version") or 1) == self.targets[kind]

    @abstractmethod
    def transform(self, query: dict) -> dict:
        raise NotImplementedError
