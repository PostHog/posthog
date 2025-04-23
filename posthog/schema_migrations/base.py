from abc import ABC, abstractmethod

from posthog.schema import NodeKind


class SchemaMigration(ABC):
    """
    Base class for schema migrations. Bumps the schema of one or more query types by one version.

    Subclasses must define:
    * `targets`: A mapping of node kinds to the version before running the migration.
    * `transform`: A method that takes a dict query and returns a new dict query with the updated schema version.
    """

    targets: dict[NodeKind, int] = {}

    def __call__(self, doc: dict) -> dict:
        """Apply if version matches, otherwise return untouched."""
        if not self.should_run(doc):
            return doc
        doc = self.transform(doc)
        doc["v"] = self.targets[doc["kind"]] + 1  # bump version
        return doc

    def should_run(self, doc: dict) -> bool:
        kind = doc.get("kind")
        return kind in self.targets and doc.get("v", 1) == self.targets[kind]

    @abstractmethod
    def transform(self, doc: dict) -> dict:
        raise NotImplementedError
