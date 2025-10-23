from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest, _create_event, flush_persons_and_events

from posthog.models import Action
from posthog.models.property_definition import PropertyDefinition
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit


class DummyToolkit(TaxonomyAgentToolkit):
    def get_tools(self):
        return self._get_default_tools()


class TestEvents(ClickhouseTestMixin, NonAtomicBaseTest):
    def setUp(self):
        super().setUp()
        for i, group_type in enumerate(["organization", "project"]):
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type_index=i, group_type=group_type
            )

        PropertyDefinition.objects.create(
            team=self.team,
            name="$browser",
            property_type="String",
            is_numerical=False,
            type=PropertyDefinition.Type.EVENT,
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="id",
            property_type="String",
            is_numerical=False,
            type=PropertyDefinition.Type.EVENT,
        )

        PropertyDefinition.objects.create(
            team=self.team,
            name="no_values",
            property_type="Boolean",
            is_numerical=False,
            type=PropertyDefinition.Type.EVENT,
        )

        # Create events that match the action conditions
        _create_event(
            event="event1",
            distinct_id="user123",
            team=self.team,
            properties={
                "$browser": "Chrome",
                "id": "123",
            },
        )

        _create_event(
            event="event1",
            distinct_id="user456",
            team=self.team,
            properties={
                "$browser": "Firefox",
                "id": "456",
            },
        )

        _create_event(
            event="no-properties-event",
            distinct_id="user456",
            team=self.team,
            properties={},
        )

        Action.objects.create(
            id=232, team=self.team, name="action1", description="Test Description", steps_json=[{"event": "event1"}]
        )

        self.toolkit = DummyToolkit(self.team, self.user)

    async def test_events_property_values_exists(self):
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project"]
        assert result == expected

        property_vals = await self.toolkit.retrieve_event_or_action_property_values({"event1": ["$browser", "id"]})
        assert "event1" in property_vals
        assert "$browser" in "\n".join(property_vals.get("event1", []))
        assert "id" in "\n".join(property_vals.get("event1", []))

    async def test_events_property_values_do_not_exist(self):
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project"]
        assert result == expected

        property_vals = await self.toolkit.retrieve_event_or_action_property_values({"event1": ["no_values"]})

        assert "event1" in property_vals
        assert "no_values" in "\n".join(property_vals.get("event1", []))
        assert "No values found for property no_values on entity event event1" in "\n".join(
            property_vals.get("event1", [])
        )

    async def test_events_property_values_action_values_not_found(self):
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project"]
        assert result == expected

        property_vals = await self.toolkit.retrieve_event_or_action_property_values({232: ["no_values"]})

        assert 232 in property_vals
        assert "no_values" in "\n".join(property_vals.get(232, []))
        assert "No values found for property no_values on entity action with ID 232" in "\n".join(
            property_vals.get(232, [])
        )

    async def test_events_property_values_action_multiple_properties(self):
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project"]
        assert result == expected

        property_vals = await self.toolkit.retrieve_event_or_action_property_values({232: ["no_values", "$browser"]})

        assert 232 in property_vals
        assert "no_values" in "\n".join(property_vals.get(232, []))
        assert "$browser" in "\n".join(property_vals.get(232, []))
        # Should have actual values
        assert "Chrome" in "\n".join(property_vals.get(232, []))
        assert "Firefox" in "\n".join(property_vals.get(232, []))

    async def test_retrieve_event_or_action_properties_action_not_found(self):
        result = await self.toolkit.retrieve_event_or_action_properties_parallel([999])
        assert (
            "Action 999 does not exist in the taxonomy. Verify that the action ID is correct and try again."
            == result["999"]
        )

    async def test_retrieve_event_or_action_properties_event_not_found(self):
        result = await self.toolkit.retrieve_event_or_action_properties_parallel(["test"])
        assert "Properties do not exist in the taxonomy for the event test." == result["test"]

    async def test_retrieve_event_or_action_properties_action_mixed(self):
        result = await self.toolkit.retrieve_event_or_action_properties_parallel([232, "event1"])

        assert "event1" in result
        assert (
            "<properties><String><prop><name>id</name></prop><prop><name>$browser</name><description>Name of the browser the user has used.</description></prop></String></properties>"
            == result["event1"]
        )
        assert "<properties>" in result["232"]

    async def test_retrieve_event_or_action_properties_action_no_properties(self):
        result = await self.toolkit.retrieve_event_or_action_properties_parallel([232, "no-properties-event"])

        assert "no-properties-event" in result
        assert (
            "Properties do not exist in the taxonomy for the event no-properties-event."
            == result["no-properties-event"]
        )
        assert "<properties>" in result["232"]

    def tearDown(self):
        flush_persons_and_events()
        super().tearDown()
