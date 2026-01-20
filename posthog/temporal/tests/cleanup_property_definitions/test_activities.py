"""Integration tests for cleanup_property_definitions activities."""

import pytest

from asgiref.sync import sync_to_async

from posthog.models import PropertyDefinition
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


@pytest.mark.django_db(transaction=True)
class TestDeletePropertyDefinitionsFromPostgres:
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
    async def test_deletes_matching_person_properties(self):
        prop_names = [f"{self.prefix}_temp_prop_{i}" for i in range(3)]
        self.created_property_names.extend(prop_names)

        @sync_to_async
        def create_properties():
            for name in prop_names:
                PropertyDefinition.objects.create(
                    team=self.team,
                    name=name,
                    type=PropertyDefinition.Type.PERSON,
                )

        await create_properties()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_temp_.*",
                property_type=PropertyDefinition.Type.PERSON,
            ),
        )

        assert result == 3

        @sync_to_async
        def verify_deleted():
            return PropertyDefinition.objects.filter(
                team=self.team,
                name__startswith=self.prefix,
                type=PropertyDefinition.Type.PERSON,
            ).count()

        remaining = await verify_deleted()
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_does_not_delete_event_properties(self):
        person_prop = f"{self.prefix}_person_prop"
        event_prop = f"{self.prefix}_event_prop"
        self.created_property_names.extend([person_prop, event_prop])

        @sync_to_async
        def create_properties():
            PropertyDefinition.objects.create(
                team=self.team,
                name=person_prop,
                type=PropertyDefinition.Type.PERSON,
            )
            PropertyDefinition.objects.create(
                team=self.team,
                name=event_prop,
                type=PropertyDefinition.Type.EVENT,
            )

        await create_properties()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_.*",
                property_type=PropertyDefinition.Type.PERSON,
            ),
        )

        # Should only delete the person property
        assert result == 1

        @sync_to_async
        def verify_event_remains():
            return PropertyDefinition.objects.filter(
                team=self.team,
                name=event_prop,
                type=PropertyDefinition.Type.EVENT,
            ).exists()

        assert await verify_event_remains()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_matches(self):
        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern="^nonexistent_pattern_.*",
                property_type=PropertyDefinition.Type.PERSON,
            ),
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_raises_error_for_invalid_team(self):
        with pytest.raises(CleanupPropertyDefinitionsError, match="Team 99999999 not found"):
            await self.activity_environment.run(
                delete_property_definitions_from_postgres,
                DeletePostgresPropertyDefinitionsInput(
                    team_id=99999999,
                    pattern="^test_.*",
                    property_type=PropertyDefinition.Type.PERSON,
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
            PropertyDefinition.objects.create(
                team=self.team,
                name=prop_name,
                type=PropertyDefinition.Type.PERSON,
            )
            PropertyDefinition.objects.create(
                team=other_team,
                name=prop_name,
                type=PropertyDefinition.Type.PERSON,
            )

        await create_properties()

        result = await self.activity_environment.run(
            delete_property_definitions_from_postgres,
            DeletePostgresPropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_.*",
                property_type=PropertyDefinition.Type.PERSON,
            ),
        )

        assert result == 1

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


@pytest.mark.django_db(transaction=True)
class TestDeletePropertyDefinitionsFromClickHouse:
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
    async def test_deletes_matching_person_properties(self):
        prop_names = [f"{self.prefix}_temp_prop_{i}" for i in range(3)]
        self.created_property_names.extend(prop_names)

        for name in prop_names:
            insert_property_definition_to_ch(self.team.id, name, property_type=2)

        # Verify properties exist
        before = get_ch_property_definitions(self.team.id, property_type=2)
        matching_before = [p for p in before if p["name"].startswith(self.prefix)]
        assert len(matching_before) == 3

        await self.activity_environment.run(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_temp_.*",
                property_type=PropertyDefinition.Type.PERSON,
            ),
        )

        # Verify properties are deleted
        after = get_ch_property_definitions(self.team.id, property_type=2)
        matching_after = [p for p in after if p["name"].startswith(self.prefix)]
        assert len(matching_after) == 0

    @pytest.mark.asyncio
    async def test_does_not_delete_event_properties(self):
        person_prop = f"{self.prefix}_person_prop"
        event_prop = f"{self.prefix}_event_prop"
        self.created_property_names.extend([person_prop, event_prop])

        insert_property_definition_to_ch(self.team.id, person_prop, property_type=2)
        insert_property_definition_to_ch(self.team.id, event_prop, property_type=1)

        await self.activity_environment.run(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_.*",
                property_type=PropertyDefinition.Type.PERSON,
            ),
        )

        # Person property should be deleted
        person_props = get_ch_property_definitions(self.team.id, property_type=2)
        assert not any(p["name"] == person_prop for p in person_props)

        # Event property should remain
        event_props = get_ch_property_definitions(self.team.id, property_type=1)
        assert any(p["name"] == event_prop for p in event_props)

        # Cleanup event property
        cleanup_ch_property_definitions(self.team.id, [event_prop])

    @pytest.mark.asyncio
    async def test_handles_no_matching_properties(self):
        # Should not raise an error
        await self.activity_environment.run(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=self.team.id,
                pattern="^nonexistent_pattern_.*",
                property_type=PropertyDefinition.Type.PERSON,
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

        insert_property_definition_to_ch(self.team.id, prop_name, property_type=2)
        insert_property_definition_to_ch(other_team.id, prop_name, property_type=2)

        await self.activity_environment.run(
            delete_property_definitions_from_clickhouse,
            DeleteClickHousePropertyDefinitionsInput(
                team_id=self.team.id,
                pattern=f"^{self.prefix}_.*",
                property_type=PropertyDefinition.Type.PERSON,
            ),
        )

        # This team's property should be deleted
        this_team_props = get_ch_property_definitions(self.team.id, property_type=2)
        assert not any(p["name"] == prop_name for p in this_team_props)

        # Other team's property should remain
        other_team_props = get_ch_property_definitions(other_team.id, property_type=2)
        assert any(p["name"] == prop_name for p in other_team_props)

        # Cleanup
        @sync_to_async
        def cleanup():
            cleanup_ch_property_definitions(other_team.id, [prop_name])
            other_team.delete()

        await cleanup()
