from typing import Any
import logging

from ee.hogai.django_checkpoint.migrations.base import BaseMigration
from ee.hogai.django_checkpoint.serializer import CheckpointContext
from ee.hogai.utils.types import GraphContext

logger = logging.getLogger(__name__)


class Migration0001(BaseMigration):
    """
    EXAMPLE ONLY - Delete this file after we've created real migrations.
    """

    def migrate_data(
        self, data: dict[str, Any], type_hint: str, context: CheckpointContext
    ) -> tuple[dict[str, Any], str]:
        if type_hint == "AssistantState" and context.graph_context == GraphContext.ROOT:
            if data.get("foo") is None:
                data["foo"] = "bar"

        return data, type_hint


# Not registered as it's an example
# migration_registry.register_migration(Migration0001)
