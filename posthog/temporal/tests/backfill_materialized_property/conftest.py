"""Fixtures for materialized property backfill tests."""

import random

import pytest

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition

from products.event_definitions.backend.models.property_definition import PropertyType


@pytest.fixture
def property_definition(team):
    """Create a test property definition."""
    return PropertyDefinition.objects.create(
        team=team,
        name=f"test_property_{random.randint(1, 99999)}",
        property_type=PropertyType.String,
        type=PropertyDefinition.Type.EVENT,
    )


@pytest.fixture
def string_property_definition(team):
    """Create a String type property definition."""
    return PropertyDefinition.objects.create(
        team=team,
        name=f"string_prop_{random.randint(1, 99999)}",
        property_type=PropertyType.String,
        type=PropertyDefinition.Type.EVENT,
    )


@pytest.fixture
def materialized_slot(team, property_definition):
    return MaterializedColumnSlot.objects.create(
        team=team,
        property_definition=property_definition,
        slot_index=0,
        state=MaterializedColumnSlotState.BACKFILL,
    )


@pytest.fixture
def materialized_slot_ready(team, property_definition):
    return MaterializedColumnSlot.objects.create(
        team=team,
        property_definition=property_definition,
        slot_index=0,
        state=MaterializedColumnSlotState.READY,
    )


@pytest.fixture
def materialized_slot_error(team, property_definition):
    return MaterializedColumnSlot.objects.create(
        team=team,
        property_definition=property_definition,
        slot_index=0,
        state=MaterializedColumnSlotState.ERROR,
        error_message="Test error message",
    )


@pytest_asyncio.fixture
async def aproperty_definition(ateam):
    return await sync_to_async(PropertyDefinition.objects.create)(
        team=ateam,
        name=f"test_property_{random.randint(1, 99999)}",
        property_type=PropertyType.String,
        type=PropertyDefinition.Type.EVENT,
    )


@pytest_asyncio.fixture
async def amaterialized_slot(ateam, aproperty_definition):
    return await sync_to_async(MaterializedColumnSlot.objects.create)(
        team=ateam,
        property_definition=aproperty_definition,
        slot_index=0,
        state=MaterializedColumnSlotState.BACKFILL,
    )
