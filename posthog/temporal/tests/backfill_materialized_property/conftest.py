"""Fixtures for materialized property backfill tests."""

import random

import pytest

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.property_definition import PropertyType


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
def numeric_property_definition(team):
    """Create a Numeric type property definition."""
    return PropertyDefinition.objects.create(
        team=team,
        name=f"numeric_prop_{random.randint(1, 99999)}",
        property_type=PropertyType.Numeric,
        type=PropertyDefinition.Type.EVENT,
    )


@pytest.fixture
def boolean_property_definition(team):
    """Create a Boolean type property definition."""
    return PropertyDefinition.objects.create(
        team=team,
        name=f"bool_prop_{random.randint(1, 99999)}",
        property_type=PropertyType.Boolean,
        type=PropertyDefinition.Type.EVENT,
    )


@pytest.fixture
def datetime_property_definition(team):
    """Create a DateTime type property definition."""
    return PropertyDefinition.objects.create(
        team=team,
        name=f"datetime_prop_{random.randint(1, 99999)}",
        property_type=PropertyType.Datetime,
        type=PropertyDefinition.Type.EVENT,
    )


@pytest.fixture
def materialized_slot(team, property_definition):
    """Create a test materialized column slot in BACKFILL state."""
    return MaterializedColumnSlot.objects.create(
        team=team,
        property_name=property_definition.name,
        property_type=property_definition.property_type,
        slot_index=0,
        state=MaterializedColumnSlotState.BACKFILL,
    )


@pytest.fixture
def materialized_slot_ready(team, property_definition):
    """Create a test materialized column slot in READY state."""
    return MaterializedColumnSlot.objects.create(
        team=team,
        property_name=property_definition.name,
        property_type=property_definition.property_type,
        slot_index=0,
        state=MaterializedColumnSlotState.READY,
    )


@pytest.fixture
def materialized_slot_error(team, property_definition):
    """Create a test materialized column slot in ERROR state."""
    return MaterializedColumnSlot.objects.create(
        team=team,
        property_name=property_definition.name,
        property_type=property_definition.property_type,
        slot_index=0,
        state=MaterializedColumnSlotState.ERROR,
        error_message="Test error message",
    )


@pytest_asyncio.fixture
async def aproperty_definition(ateam):
    """Create a test property definition (async)."""
    return await sync_to_async(PropertyDefinition.objects.create)(
        team=ateam,
        name=f"test_property_{random.randint(1, 99999)}",
        property_type=PropertyType.String,
        type=PropertyDefinition.Type.EVENT,
    )


@pytest_asyncio.fixture
async def amaterialized_slot(ateam, aproperty_definition):
    """Create a test materialized column slot (async)."""
    return await sync_to_async(MaterializedColumnSlot.objects.create)(
        team=ateam,
        property_name=aproperty_definition.name,
        property_type=aproperty_definition.property_type,
        slot_index=0,
        state=MaterializedColumnSlotState.BACKFILL,
    )
