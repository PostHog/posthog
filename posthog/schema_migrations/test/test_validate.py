import pytest
from unittest.mock import MagicMock

from posthog.schema import NodeKind

from posthog.schema_migrations import MIGRATIONS
from posthog.schema_migrations.validate import validate_migrations


def test_linear():
    """Validation of the actual migrations."""
    validate_migrations()


def test_validate_migrations():
    MIGRATIONS.clear()
    MIGRATIONS[NodeKind.TRENDS_QUERY] = {1: MagicMock()}
    MIGRATIONS[NodeKind.EVENTS_NODE] = {1: MagicMock()}

    # Should not raise
    validate_migrations()

    # Gap in versions for EVENTS_NODE
    MIGRATIONS[NodeKind.EVENTS_NODE] = {1: MagicMock(), 3: MagicMock()}
    with pytest.raises(Exception):
        validate_migrations()

    # Wrong order of versions for EVENTS_NODE
    MIGRATIONS[NodeKind.EVENTS_NODE] = {2: MagicMock(), 1: MagicMock()}
    with pytest.raises(Exception):
        validate_migrations()
