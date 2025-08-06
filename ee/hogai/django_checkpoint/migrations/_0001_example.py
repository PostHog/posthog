from typing import Any
import logging

from ee.hogai.django_checkpoint.migrations.base import BaseMigration

logger = logging.getLogger(__name__)


class Migration0001(BaseMigration):
    """
    EXAMPLE ONLY - Delete this file after we've created real migrations.
    """

    def migrate_data(self, data: dict[str, Any], type_hint: str) -> tuple[dict[str, Any], str]:
        if type_hint == "AssistantState":
            if data.get("foo") is None:
                data["foo"] = "bar"

        return data, type_hint


# Not registered as it's an example
# migration_registry.register_migration(Migration0001)
