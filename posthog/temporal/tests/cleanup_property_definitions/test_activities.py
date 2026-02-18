"""Integration tests for cleanup_property_definitions activities."""

import pytest

from asgiref.sync import sync_to_async
from parameterized import parameterized_class

from posthog.models import PropertyDefinition
from posthog.models.event_property import EventProperty
from posthog.temporal.cleanup_property_definitions.activities import (
    delete_property_definitions_from_clickhouse,
    delete_property_definitions_from_postgres,
)
from posthog.temporal.cleanup_property_definitions.types import (
    CleanupPropertyDefinitionsError,
    DeleteClickHousePropertyDefinitionsInput,
    DeletePostgresPropertyDefinitionsInput,
)
from posthog.temporal.tests.cleanup_property_definitions.conftest import (
    cleanup_ch_property_definitions,
    get_ch_property_definitions,
    insert_property_definition_to_ch,
)


def create_property_definition(team, name: str, property_type: int) -> PropertyDefinition:
    """Create a PropertyDefinition with the correct fields for the given type.

    GROUP type requires group_type_index to be set due to database constraint.
    """
    kwargs = {"team": team, "name": name, "type": property_type}
    if property_type == PropertyDefinition.Type.GROUP:
        kwargs["group_type_index"] = 0
    return PropertyDefinition.objects.create(**kwargs)


@parameterized_class(
    ("property_type", "property_type_int"),
    [
        (PropertyDefinition.Type.EVENT, 1),
        (PropertyDefinition.Type.PERSON, 2),
        (PropertyDefinition.Type.GROUP, 3),
        (PropertyDefinition.Type.SESSION, 4),
    ],
)
@pytest.mark.django_db(transaction=True)
class TestDeletePropertyDefinitionsFromPostgres:
    property_type: int
    property_type_int: int

    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix, activity_environment):
        self.team = team
        self.prefix = test_prefix
        self.activity_environment = activity_environment
        self.created_property_names: list[str] = []

        yield

        # Cleanup PostgreSQL
        PropertyDefinition.objects.filter(
            team=self.team,
            name__startswith=self.prefix,
        ).delete()

    @pytest.mark.asyncio
    async def test_deletes_matching_properties(self):
        prop_names = [f"{self.prefix}_temp_prop_{i}" for i in range(3)]
        self.created_property_names.extend(prop_names)

        @sync_to_async
        def create_properties():
            for name in prop_names:
                create_property_definition(self.team, name, self.property_type)

        await create_properties()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_temp_.*",
                property_type=self.property_type,
            ),
        )

        assert result["property_definitions_deleted"] == 3

        @sync_to_async
        def verify_deleted():
            return PropertyDefinition.objects.filter(
                team=self.team,
                name__startswith=self.prefix,
                type=self.property_type,
            ).count()

        remaining = await verify_deleted()
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_does_not_delete_other_property_types(self):
        # Get a different property type to test isolation
        other_type = (
            PropertyDefinition.Type.EVENT
            if self.property_type != PropertyDefinition.Type.EVENT
            else PropertyDefinition.Type.PERSON
        )

        target_prop = f"{self.prefix}_target_prop"
        other_prop = f"{self.prefix}_other_prop"
        self.created_property_names.extend([target_prop, other_prop])

        @sync_to_async
        def create_properties():
            create_property_definition(self.team, target_prop, self.property_type)
            create_property_definition(self.team, other_prop, other_type)

        await create_properties()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_.*",
                property_type=self.property_type,
            ),
        )

        # Should only delete the target property type
        assert result["property_definitions_deleted"] == 1

        @sync_to_async
        def verify_other_remains():
            return PropertyDefinition.objects.filter(
                team=self.team,
                name=other_prop,
                type=other_type,
            ).exists()

        assert await verify_other_remains()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_matches(self):
        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern="^nonexistent_pattern_.*",
                property_type=self.property_type,
            ),
        )

        assert result["property_definitions_deleted"] == 0
        assert result["event_properties_deleted"] == 0

    @pytest.mark.asyncio
    async def test_raises_error_for_invalid_team(self):
        with pytest.raises(CleanupPropertyDefinitionsError, match="Team 99999999 not found"):
            await self.activity_environment.run(
                delete_property_definitions_from_postgres,
                DeletePostgresPropertyDefinitionsInput(
                    team_id=99999999,
                    pattern="^test_.*",
                    property_type=self.property_type,
                ),
            )

    @pytest.mark.asyncio
    async def test_does_not_delete_other_teams_properties(self, organization):
        from posthog.models import Team

        @sync_to_async
        def create_other_team():
            return Team.objects.create(organization=organization, name="Other Team")

        other_team = await create_other_team()

        prop_name = f"{self.prefix}_shared_prop"
        self.created_property_names.append(prop_name)

        @sync_to_async
        def create_properties():
            create_property_definition(self.team, prop_name, self.property_type)
            create_property_definition(other_team, prop_name, self.property_type)

        await create_properties()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_.*",
                property_type=self.property_type,
            ),
        )

        assert result["property_definitions_deleted"] == 1

        @sync_to_async
        def verify_other_team_property():
            return PropertyDefinition.objects.filter(
                team=other_team,
                name=prop_name,
            ).exists()

        assert await verify_other_team_property()

        # Cleanup other team
        @sync_to_async
        def cleanup():
            PropertyDefinition.objects.filter(team=other_team).delete()
            other_team.delete()

        await cleanup()

    @pytest.mark.asyncio
    async def test_deletes_in_batches(self):
        prop_names = [f"{self.prefix}_batch_prop_{i}" for i in range(5)]
        self.created_property_names.extend(prop_names)

        @sync_to_async
        def create_properties():
            for name in prop_names:
                create_property_definition(self.team, name, self.property_type)

        await create_properties()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_batch_.*",
                property_type=self.property_type,
                batch_size=2,
            ),
        )

        assert result["property_definitions_deleted"] == 2

        @sync_to_async
        def count_remaining():
            return PropertyDefinition.objects.filter(
                team=self.team,
                name__startswith=f"{self.prefix}_batch_",
                type=self.property_type,
            ).count()

        remaining = await count_remaining()
        assert remaining == 3


@pytest.mark.django_db(transaction=True)
class TestDeleteEventPropertiesFromPostgres:
    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix, activity_environment):
        self.team = team
        self.prefix = test_prefix
        self.activity_environment = activity_environment

        yield

        PropertyDefinition.objects.filter(team=self.team, name__startswith=self.prefix).delete()
        EventProperty.objects.filter(team=self.team, property__startswith=self.prefix).delete()

    @pytest.mark.asyncio
    async def test_deletes_event_properties_for_event_type(self):
        prop_names = [f"{self.prefix}_temp_prop_{i}" for i in range(3)]

        @sync_to_async
        def create_data():
            for name in prop_names:
                create_property_definition(self.team, name, PropertyDefinition.Type.EVENT)
                EventProperty.objects.create(team=self.team, event="$pageview", property=name)
                EventProperty.objects.create(team=self.team, event="$autocapture", property=name)

        await create_data()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_temp_.*",
                property_type=PropertyDefinition.Type.EVENT,
            ),
        )

        assert result["property_definitions_deleted"] == 3
        assert result["event_properties_deleted"] == 6

        @sync_to_async
        def verify_deleted():
            return EventProperty.objects.filter(team=self.team, property__startswith=self.prefix).count()

        assert await verify_deleted() == 0

    @pytest.mark.asyncio
    async def test_deletes_event_properties_for_person_type(self):
        prop_name = f"{self.prefix}_person_prop"

        @sync_to_async
        def create_data():
            create_property_definition(self.team, prop_name, PropertyDefinition.Type.PERSON)
            EventProperty.objects.create(team=self.team, event="$pageview", property=prop_name)

        await create_data()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_person_.*",
                property_type=PropertyDefinition.Type.PERSON,
            ),
        )

        assert result["property_definitions_deleted"] == 1
        assert result["event_properties_deleted"] == 1

        @sync_to_async
        def verify_event_property_deleted():
            return EventProperty.objects.filter(team=self.team, property=prop_name).exists()

        assert not await verify_event_property_deleted()

    @pytest.mark.asyncio
    async def test_deletes_in_batches_with_corresponding_event_properties(self):
        prop_names = [f"{self.prefix}_batch_prop_{i}" for i in range(5)]

        @sync_to_async
        def create_data():
            for name in prop_names:
                create_property_definition(self.team, name, PropertyDefinition.Type.EVENT)
                EventProperty.objects.create(team=self.team, event="$pageview", property=name)

        await create_data()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_batch_.*",
                property_type=PropertyDefinition.Type.EVENT,
                batch_size=2,
            ),
        )

        assert result["property_definitions_deleted"] == 2
        assert result["event_properties_deleted"] == 2

        @sync_to_async
        def count_remaining():
            prop_defs = PropertyDefinition.objects.filter(
                team=self.team, name__startswith=f"{self.prefix}_batch_", type=PropertyDefinition.Type.EVENT
            ).count()
            event_props = EventProperty.objects.filter(
                team=self.team, property__startswith=f"{self.prefix}_batch_"
            ).count()
            return prop_defs, event_props

        remaining_defs, remaining_event_props = await count_remaining()
        assert remaining_defs == 3
        assert remaining_event_props == 3


@parameterized_class(
    ("property_type", "property_type_int"),
    [
        (PropertyDefinition.Type.EVENT, 1),
        (PropertyDefinition.Type.PERSON, 2),
        (PropertyDefinition.Type.GROUP, 3),
        (PropertyDefinition.Type.SESSION, 4),
    ],
)
@pytest.mark.django_db(transaction=True)
class TestDeletePropertyDefinitionsFromClickHouse:
    property_type: int
    property_type_int: int

    @pytest.fixture(autouse=True)
    def setup(self, team, test_prefix, activity_environment):
        self.team = team
        self.prefix = test_prefix
        self.activity_environment = activity_environment
        self.created_property_names: list[str] = []

        yield

        # Cleanup ClickHouse
        cleanup_ch_property_definitions(self.team.id, self.created_property_names)

    @pytest.mark.asyncio
    async def test_deletes_matching_properties(self):
        prop_names = [f"{self.prefix}_temp_prop_{i}" for i in range(3)]
        self.created_property_names.extend(prop_names)

        for name in prop_names:
            insert_property_definition_to_ch(self.team.id, name, property_type=self.property_type_int)

        # Verify properties exist
        before = get_ch_property_definitions(self.team.id, property_type=self.property_type_int)
        matching_before = [p for p in before if p["name"].startswith(self.prefix)]
        assert len(matching_before) == 3

        await self.activity_environment.run(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_temp_.*",
                property_type=self.property_type,
            ),
        )

        # Verify properties are deleted
        after = get_ch_property_definitions(self.team.id, property_type=self.property_type_int)
        matching_after = [p for p in after if p["name"].startswith(self.prefix)]
        assert len(matching_after) == 0

    @pytest.mark.asyncio
    async def test_does_not_delete_other_property_types(self):
        # Get a different property type to test isolation
        other_type = 1 if self.property_type_int != 1 else 2

        target_prop = f"{self.prefix}_target_prop"
        other_prop = f"{self.prefix}_other_prop"
        self.created_property_names.extend([target_prop, other_prop])

        insert_property_definition_to_ch(self.team.id, target_prop, property_type=self.property_type_int)
        insert_property_definition_to_ch(self.team.id, other_prop, property_type=other_type)

        await self.activity_environment.run(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_.*",
                property_type=self.property_type,
            ),
        )

        # Target property should be deleted
        target_props = get_ch_property_definitions(self.team.id, property_type=self.property_type_int)
        assert not any(p["name"] == target_prop for p in target_props)

        # Other property should remain
        other_props = get_ch_property_definitions(self.team.id, property_type=other_type)
        assert any(p["name"] == other_prop for p in other_props)

        # Cleanup other property
        cleanup_ch_property_definitions(self.team.id, [other_prop])

    @pytest.mark.asyncio
    async def test_handles_no_matching_properties(self):
        # Should not raise an error
        await self.activity_environment.run(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=self.team.id,
                pattern="^nonexistent_pattern_.*",
                property_type=self.property_type,
            ),
        )

    @pytest.mark.asyncio
    async def test_does_not_delete_other_teams_properties(self, organization):
        from posthog.models import Team

        @sync_to_async
        def create_other_team():
            return Team.objects.create(organization=organization, name="Other Team")

        other_team = await create_other_team()

        prop_name = f"{self.prefix}_shared_prop"
        self.created_property_names.append(prop_name)

        insert_property_definition_to_ch(self.team.id, prop_name, property_type=self.property_type_int)
        insert_property_definition_to_ch(other_team.id, prop_name, property_type=self.property_type_int)

        await self.activity_environment.run(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_.*",
                property_type=self.property_type,
            ),
        )

        # This team's property should be deleted
        this_team_props = get_ch_property_definitions(self.team.id, property_type=self.property_type_int)
        assert not any(p["name"] == prop_name for p in this_team_props)

        # Other team's property should remain
        other_team_props = get_ch_property_definitions(other_team.id, property_type=self.property_type_int)
        assert any(p["name"] == prop_name for p in other_team_props)

        # Cleanup
        @sync_to_async
        def cleanup():
            cleanup_ch_property_definitions(other_team.id, [prop_name])
            other_team.delete()

        await cleanup()
