from datetime import datetime
from textwrap import dedent

from freezegun import freeze_time

from ee.hogai.graph.taxonomy_agent.toolkit import FinalAnswerTool, TaxonomyAgentToolkit, ToolkitTool
from posthog.models import Action
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.test.base import BaseTest, ClickhouseTestMixin, NonAtomicBaseTest, _create_event, _acreate_person
from asgiref.sync import sync_to_async


class DummyToolkit(TaxonomyAgentToolkit):
    async def _get_tools(self) -> list[ToolkitTool]:
        return await self._default_tools()


class TestTaxonomyAgentToolkit(ClickhouseTestMixin, NonAtomicBaseTest):
    def setUp(self):
        super().setUp()
        self.action = Action.objects.create(team=self.team, name="action1", steps_json=[{"event": "event1"}])

    async def _create_taxonomy(self):
        await PropertyDefinition.objects.abulk_create(
            [
                PropertyDefinition(
                    team=self.team,
                    type=PropertyDefinition.Type.EVENT,
                    name="$browser",
                    property_type=PropertyType.String,
                ),
                PropertyDefinition(
                    team=self.team, type=PropertyDefinition.Type.EVENT, name="id", property_type=PropertyType.Numeric
                ),
                PropertyDefinition(
                    team=self.team, type=PropertyDefinition.Type.EVENT, name="bool", property_type=PropertyType.Boolean
                ),
                PropertyDefinition(
                    team=self.team, type=PropertyDefinition.Type.EVENT, name="date", property_type=PropertyType.Datetime
                ),
            ]
        )

        await _acreate_person(
            distinct_ids=["person1"],
            team=self.team,
            properties={"email": "person1@example.com"},
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={
                "$browser": "Chrome",
                "date": datetime(2024, 1, 1).isoformat(),
            },
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={
                "$browser": "Firefox",
                "bool": True,
            },
            team=self.team,
        )

        await _acreate_person(
            distinct_ids=["person2"],
            properties={"email": "person2@example.com"},
            team=self.team,
        )
        for i in range(10):
            _create_event(
                event="event1",
                distinct_id=f"person2",
                properties={"id": i},
                team=self.team,
            )

    async def test_retrieve_entity_properties(self):
        toolkit = DummyToolkit(self.team)

        await PropertyDefinition.objects.acreate(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="test", property_type="String"
        )
        self.assertEqual(
            await toolkit.retrieve_entity_properties("person"),
            "<properties><String><prop><name>test</name></prop></String></properties>",
        )

        await GroupTypeMapping.objects.acreate(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="group"
        )
        await PropertyDefinition.objects.acreate(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=0, name="test", property_type="Numeric"
        )
        self.assertEqual(
            await toolkit.retrieve_entity_properties("group"),
            "<properties><Numeric><prop><name>test</name></prop></Numeric></properties>",
        )

        self.assertNotEqual(
            await toolkit.retrieve_entity_properties("session"),
            "<properties />",
        )
        self.assertIn(
            "$session_duration",
            await toolkit.retrieve_entity_properties("session"),
        )

    async def test_retrieve_entity_properties_returns_descriptive_feedback_without_properties(self):
        toolkit = DummyToolkit(self.team)
        self.assertEqual(
            await toolkit.retrieve_entity_properties("person"),
            "Properties do not exist in the taxonomy for the entity person.",
        )

    async def test_retrieve_entity_property_values(self):
        toolkit = DummyToolkit(self.team)
        self.assertEqual(
            await toolkit.retrieve_entity_property_values("session", "$session_duration"),
            "30, 146, 2 and many more distinct values.",
        )
        self.assertEqual(
            await toolkit.retrieve_entity_property_values("session", "nonsense"),
            "The property nonsense does not exist in the taxonomy.",
        )

        await PropertyDefinition.objects.acreate(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="email", property_type=PropertyType.String
        )
        await PropertyDefinition.objects.acreate(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="id", property_type=PropertyType.Numeric
        )

        for i in range(25):
            id = f"person{i}"
            with freeze_time(f"2024-01-01T00:{i}:00Z"):
                await _acreate_person(
                    distinct_ids=[id],
                    properties={"email": f"{id}@example.com", "id": i},
                    team=self.team,
                )
        with freeze_time(f"2024-01-02T00:00:00Z"):
            await _acreate_person(
                distinct_ids=["person25"],
                properties={"email": "person25@example.com", "id": 25},
                team=self.team,
            )

        self.assertIn(
            '"person5@example.com", "person4@example.com", "person3@example.com", "person2@example.com", "person1@example.com"',
            await toolkit.retrieve_entity_property_values("person", "email"),
        )
        self.assertIn(
            "1 more distinct value",
            await toolkit.retrieve_entity_property_values("person", "id"),
        )

        toolkit = DummyToolkit(self.team)
        await GroupTypeMapping.objects.acreate(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="proj"
        )
        await GroupTypeMapping.objects.acreate(
            team=self.team, project_id=self.team.project_id, group_type_index=1, group_type="org"
        )
        await PropertyDefinition.objects.acreate(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=0, name="test", property_type="Numeric"
        )
        await PropertyDefinition.objects.acreate(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=1, name="test", property_type="String"
        )

        for i in range(7):
            id = f"group{i}"
            with freeze_time(f"2024-01-01T{i}:00:00Z"):
                sync_to_async(create_group)(
                    group_type_index=0,
                    group_key=id,
                    properties={"test": i},
                    team_id=self.team.pk,
                )
        with freeze_time(f"2024-01-02T00:00:00Z"):
            sync_to_async(create_group)(
                group_type_index=1,
                group_key="org",
                properties={"test": "7"},
                team_id=self.team.pk,
            )

        self.assertEqual(
            await toolkit.retrieve_entity_property_values("proj", "test"),
            "6, 5, 4, 3, 2, 1, 0",
        )
        self.assertEqual(await toolkit.retrieve_entity_property_values("org", "test"), '"7"')

    async def test_group_names(self):
        await GroupTypeMapping.objects.acreate(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="proj"
        )
        await GroupTypeMapping.objects.acreate(
            team=self.team, project_id=self.team.project_id, group_type_index=1, group_type="org"
        )
        toolkit = DummyToolkit(self.team)
        self.assertEqual(await toolkit._entity_names(), ["person", "session", "proj", "org"])

    async def test_retrieve_event_properties_returns_descriptive_feedback_without_properties(self):
        toolkit = DummyToolkit(self.team)
        self.assertEqual(
            await toolkit.retrieve_event_or_action_properties("pageview"),
            "Properties do not exist in the taxonomy for the event pageview.",
        )

    async def test_empty_events(self):
        toolkit = DummyToolkit(self.team)
        self.assertEqual(
            await toolkit.retrieve_event_or_action_properties("test"),
            "Properties do not exist in the taxonomy for the event test.",
        )

        await _acreate_person(
            distinct_ids=["person1"],
            team=self.team,
            properties={},
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={},
            team=self.team,
        )

        toolkit = DummyToolkit(self.team)
        self.assertEqual(
            await toolkit.retrieve_event_or_action_properties("event1"),
            "Properties do not exist in the taxonomy for the event event1.",
        )

    async def test_retrieve_event_or_action_properties(self):
        await self._create_taxonomy()
        toolkit = DummyToolkit(self.team)
        for item in ("event1", self.action.id):
            prompt = await toolkit.retrieve_event_or_action_properties(item)
            self.assertIn(
                "<Numeric><prop><name>id</name></prop></Numeric>",
                prompt,
            )
            self.assertIn(
                "<String><prop><name>$browser</name><description>Name of the browser the user has used.</description></prop></String>",
                prompt,
            )
            self.assertIn(
                "<DateTime><prop><name>date</name></prop></DateTime>",
                prompt,
            )
            self.assertIn(
                "<Boolean><prop><name>bool</name></prop></Boolean>",
                prompt,
            )

    async def test_retrieve_event_or_action_property_values(self):
        await self._create_taxonomy()
        toolkit = DummyToolkit(self.team)

        for item in ("event1", self.action.id):
            self.assertIn('"Chrome"', await toolkit.retrieve_event_or_action_property_values(item, "$browser"))
            self.assertIn('"Firefox"', await toolkit.retrieve_event_or_action_property_values(item, "$browser"))
            self.assertEqual(await toolkit.retrieve_event_or_action_property_values(item, "bool"), "true")
            self.assertEqual(
                await toolkit.retrieve_event_or_action_property_values(item, "id"),
                "9, 8, 7, 6, 5, 4, 3, 2, 1, 0",
            )
            self.assertEqual(
                await toolkit.retrieve_event_or_action_property_values(item, "date"),
                f'"{datetime(2024, 1, 1).isoformat()}"',
            )

    async def test_retrieve_event_or_action_properties_when_actions_exist_but_action_id_incorrect(self):
        toolkit = DummyToolkit(self.team)
        incorrect_action_id = self.action.id + 999  # Ensure it doesn't exist

        result = await toolkit.retrieve_event_or_action_properties(incorrect_action_id)
        self.assertEqual(
            result,
            f"Action {incorrect_action_id} does not exist in the taxonomy. Verify that the action ID is correct and try again.",
        )

    async def test_retrieve_event_or_action_properties_when_no_actions_exist_and_action_id_incorrect(self):
        await Action.objects.all().adelete()

        toolkit = DummyToolkit(self.team)
        incorrect_action_id = 9999

        result = await toolkit.retrieve_event_or_action_properties(incorrect_action_id)
        self.assertEqual(result, "No actions exist in the project.")

    async def test_enrich_props_with_descriptions(self):
        toolkit = DummyToolkit(self.team)
        res = toolkit._enrich_props_with_descriptions("event", [("$geoip_city_name", "String")])
        self.assertEqual(len(res), 1)
        prop, type, description = res[0]
        self.assertEqual(prop, "$geoip_city_name")
        self.assertEqual(type, "String")
        self.assertIsNotNone(description)


class TestFinalAnswerTool(BaseTest):
    def test_normalize_plan(self):
        original = """
        Series:
        - series 1: Interacted with file
            - action id: 1
            - math operation: unique users
            - property filter 1:
                - entity: action
                - property name: $geoip_country_code
                - property type: String
                - operator: equals
                - property value: AU
            - property filter 2:
                - action
                - property name: icp_score
                - property type: String
                - operator: equals
                - property value: 10
            - property filter 3:
                - action
                - property name: action
                - property type: String
                - operator: equals
                - property value: action
        """
        normalized = """
        Series:
        - series 1: Interacted with file
            - action id: 1
            - math operation: unique users
            - property filter 1:
                - entity: event
                - property name: $geoip_country_code
                - property type: String
                - operator: equals
                - property value: AU
            - property filter 2:
                - entity: event
                - property name: icp_score
                - property type: String
                - operator: equals
                - property value: 10
            - property filter 3:
                - entity: event
                - property name: action
                - property type: String
                - operator: equals
                - property value: action
        """
        tool = FinalAnswerTool(name="final_answer", arguments=dedent(original))
        self.assertEqual(tool.arguments.strip(), dedent(normalized).strip())
