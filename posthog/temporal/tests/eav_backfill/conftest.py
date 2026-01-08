"""Fixtures for EAV property backfill tests."""

import random

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import MaterializationType, MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.property_definition import PropertyType


@pytest_asyncio.fixture
async def aeav_property_definition(ateam):
    """Create a test property definition for EAV (async)."""
    return await sync_to_async(PropertyDefinition.objects.create)(
        team=ateam,
        name=f"eav_test_property_{random.randint(1, 99999)}",
        property_type=PropertyType.String,
        type=PropertyDefinition.Type.EVENT,
    )


@pytest_asyncio.fixture
async def aeav_slot(ateam, aeav_property_definition):
    """Create a test EAV materialized column slot (async)."""
    return await sync_to_async(MaterializedColumnSlot.objects.create)(
        team=ateam,
        property_name=aeav_property_definition.name,
        property_type=aeav_property_definition.property_type,
        slot_index=0,
        state=MaterializedColumnSlotState.BACKFILL,
        materialization_type=MaterializationType.EAV,
    )
