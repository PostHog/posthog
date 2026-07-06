from datetime import UTC, datetime, timedelta
from textwrap import dedent

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from posthog.schema import CachedActorsPropertyTaxonomyQueryResponse, CachedEventTaxonomyQueryResponse

from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import invalidate_group_types_cache
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.actions.backend.models.action import Action
from products.event_definitions.backend.models.property_definition import PropertyDefinition, PropertyType

from ee.hogai.chat_agent.query_planner.toolkit import TaxonomyAgentToolkit, final_answer


class DummyToolkit(TaxonomyAgentToolkit):
    _parent_tool_call_id: str | None = None
    pass


class TestTaxonomyAgentToolkit(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.action = Action.objects.create(team=self.team, name="action1", steps_json=[{"event": "event1"}])

    def _create_taxonomy(self):
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.EVENT, name="$browser", property_type=PropertyType.String
        )
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.EVENT, name="id", property_type=PropertyType.Numeric
        )
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.EVENT, name="bool", property_type=PropertyType.Boolean
        )
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.EVENT, name="date", property_type=PropertyType.Datetime
        )

        _create_person(
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

        _create_person(
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

    def test_retrieve_entity_properties(self):
        toolkit = DummyToolkit(self.team, self.user)

        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="test", property_type="String"
        )
        result = toolkit.retrieve_entity_properties("person")
        self.assertIn("The data format is as follows:", result)
        self.assertIn("<String>", result)
        self.assertIn("- test", result)
        self.assertIn("</String>", result)

        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="group"
        )
        invalidate_group_types_cache(self.team.project_id)
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=0, name="test", property_type="Numeric"
        )
        toolkit = DummyToolkit(self.team, self.user)
        result = toolkit.retrieve_entity_properties("group")
        self.assertIn("The data format is as follows:", result)
        self.assertIn("<Numeric>", result)
        self.assertIn("- test", result)
        self.assertIn("</Numeric>", result)

        result = toolkit.retrieve_entity_properties("session")
        self.assertIn("The data format is as follows:", result)
        self.assertIn(
            "$session_duration",
            result,
        )

    def test_retrieve_entity_properties_lists_virtual_properties_without_stored_definitions(self):
        toolkit = DummyToolkit(self.team, self.user)
        result = toolkit.retrieve_entity_properties("person")
        self.assertIn("$virt_initial_channel_type", result)
        self.assertIn("$virt_revenue", result)

    def test_retrieve_entity_property_values(self):
        toolkit = DummyToolkit(self.team, self.user)
        self.assertEqual(
            toolkit.retrieve_entity_property_values("session", "$session_duration"),
            "30, 146, 2 and many more distinct values.",
        )
        self.assertEqual(
            toolkit.retrieve_entity_property_values("session", "nonsense"),
            "The property nonsense does not exist in the taxonomy.",
        )

        PropertyDefinition.objects.create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="taxonomy_email",
            property_type=PropertyType.String,
        )
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="id", property_type=PropertyType.Numeric
        )

        # The persons HogQL table excludes rows with created_at >= now() + 1 day (see
        # select_from_persons_table in posthog/hogql/database/schema/persons.py), so timestamps
        # must stay in the real past. Anchor to the real clock and space out by minutes so each
        # person sorts deterministically by created_at regardless of when the test runs.
        base_time = datetime.now(UTC)
        for i in range(25):
            id = f"person{i}"
            with freeze_time(base_time - timedelta(minutes=25 - i)):
                _create_person(
                    distinct_ids=[id],
                    properties={"taxonomy_email": f"{id}@example.com", "id": i},
                    team=self.team,
                )
        with freeze_time(base_time):
            _create_person(
                distinct_ids=["person25"],
                properties={"taxonomy_email": "person25@example.com", "id": 25},
                team=self.team,
            )

        result = toolkit.retrieve_entity_property_values("person", "taxonomy_email")
        for person in ["person25@example.com", "person24@example.com", "person23@example.com"]:
            self.assertIn(person, result)
        self.assertIn(
            "1 more distinct value",
            toolkit.retrieve_entity_property_values("person", "id"),
        )

        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="proj"
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type_index=1, group_type="org"
        )
        invalidate_group_types_cache(self.team.project_id)
        toolkit = DummyToolkit(self.team, self.user)
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=0, name="test", property_type="Numeric"
        )
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=1, name="test", property_type="String"
        )

        for i in range(7):
            id = f"group{i}"
            with freeze_time(f"2024-01-01T{i}:00:00Z"):
                create_group(
                    group_type_index=0,
                    group_key=id,
                    properties={"test": i},
                    team_id=self.team.pk,
                )
        with freeze_time(f"2024-01-02T00:00:00Z"):
            create_group(
                group_type_index=1,
                group_key="org",
                properties={"test": "7"},
                team_id=self.team.pk,
            )

        self.assertEqual(
            toolkit.retrieve_entity_property_values("proj", "test"),
            "6, 5, 4, 3, 2, 1, 0",
        )
        self.assertEqual(toolkit.retrieve_entity_property_values("org", "test"), '"7"')

    @patch("ee.hogai.chat_agent.query_planner.toolkit.ActorsPropertyTaxonomyQueryRunner")
    def test_retrieve_entity_property_values_virtual_person_property_with_examples(self, mock_runner_class):
        # A virtual property has no stored actor values, so the toolkit falls back to
        # the taxonomy's hardcoded examples. The real runner reads ClickHouse actor
        # data, which sibling tests on the same shard can pollute (file-level sharding
        # runs the whole file together and ClickHouse writes are not rolled back per
        # test), making it return a stray "Unknown" instead of nothing. Mock an empty
        # result so this asserts the fallback deterministically; the real-runner path
        # is covered by the property-value tests that seed actual actor data.
        now = datetime(2024, 1, 1, tzinfo=UTC)
        mock_runner_class.return_value.run.return_value = CachedActorsPropertyTaxonomyQueryResponse(
            cache_key="test",
            is_cached=True,
            last_refresh=now,
            next_allowed_client_refresh=now,
            results=[],
            timezone="UTC",
        )
        toolkit = DummyToolkit(self.team, self.user)
        self.assertEqual(
            toolkit.retrieve_entity_property_values("person", "$virt_initial_channel_type"),
            '"Paid Search", "Organic Video", "Direct" and many more distinct values.',
        )

    @patch("ee.hogai.chat_agent.query_planner.toolkit.ActorsPropertyTaxonomyQueryRunner")
    def test_retrieve_entity_property_values_virtual_property_without_examples(self, mock_runner_class):
        # The real runner reads ClickHouse actor data, which sibling tests on the same
        # shard can pollute (file-level sharding runs the whole file together and
        # ClickHouse writes are not rolled back per test), making $virt_mrr resolve to a
        # stray value instead of nothing. Mock an empty result so this asserts the
        # no-values fallback deterministically.
        now = datetime(2024, 1, 1, tzinfo=UTC)
        mock_runner_class.return_value.run.return_value = CachedActorsPropertyTaxonomyQueryResponse(
            cache_key="test",
            is_cached=True,
            last_refresh=now,
            next_allowed_client_refresh=now,
            results=[],
            timezone="UTC",
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="proj"
        )
        invalidate_group_types_cache(self.team.project_id)
        toolkit = DummyToolkit(self.team, self.user)
        for entity in ("person", "proj"):
            self.assertEqual(
                toolkit.retrieve_entity_property_values(entity, "$virt_mrr"),
                "The property $virt_mrr is a virtual property computed at query time, "
                "so the taxonomy does not have stored sample values.",
            )

    @patch("ee.hogai.chat_agent.query_planner.toolkit.ActorsPropertyTaxonomyQueryRunner")
    def test_retrieve_entity_property_values_virtual_person_property_with_empty_runner_results(self, mock_runner_class):
        now = datetime(2024, 1, 1, tzinfo=UTC)
        mock_runner_class.return_value.run.return_value = CachedActorsPropertyTaxonomyQueryResponse(
            cache_key="test",
            is_cached=True,
            last_refresh=now,
            next_allowed_client_refresh=now,
            results=[],
            timezone="UTC",
        )
        toolkit = DummyToolkit(self.team, self.user)
        self.assertEqual(
            toolkit.retrieve_entity_property_values("person", "$virt_initial_channel_type"),
            '"Paid Search", "Organic Video", "Direct" and many more distinct values.',
        )

    @patch("ee.hogai.chat_agent.query_planner.toolkit.ActorsPropertyTaxonomyQueryRunner")
    def test_retrieve_entity_property_values_virtual_group_property_with_empty_runner_results(self, mock_runner_class):
        now = datetime(2024, 1, 1, tzinfo=UTC)
        mock_runner_class.return_value.run.return_value = CachedActorsPropertyTaxonomyQueryResponse(
            cache_key="test",
            is_cached=True,
            last_refresh=now,
            next_allowed_client_refresh=now,
            results=[],
            timezone="UTC",
        )
        toolkit = DummyToolkit(self.team, self.user)
        # Bypass the personhog-backed _groups lookup so the group entity is recognized.
        toolkit.__dict__["_groups"] = [{"group_type": "proj", "group_type_index": 0}]
        self.assertEqual(
            toolkit.retrieve_entity_property_values("proj", "$virt_mrr"),
            "The property $virt_mrr is a virtual property computed at query time, "
            "so the taxonomy does not have stored sample values.",
        )

    def test_group_names(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type_index=0, group_type="proj"
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type_index=1, group_type="org"
        )
        invalidate_group_types_cache(self.team.project_id)
        toolkit = DummyToolkit(self.team, self.user)
        self.assertEqual(toolkit._entity_names, ["person", "session", "proj", "org"])

    def test_retrieve_event_properties_returns_descriptive_feedback_without_properties(self):
        toolkit = DummyToolkit(self.team, self.user)
        self.assertEqual(
            toolkit.retrieve_event_or_action_properties("pageview"),
            "Properties do not exist in the taxonomy for the event pageview.",
        )

    def test_empty_events(self):
        toolkit = DummyToolkit(self.team, self.user)
        self.assertEqual(
            toolkit.retrieve_event_or_action_properties("test"),
            "Properties do not exist in the taxonomy for the event test.",
        )

        _create_person(
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

        toolkit = DummyToolkit(self.team, self.user)
        self.assertEqual(
            toolkit.retrieve_event_or_action_properties("event1"),
            "Properties do not exist in the taxonomy for the event event1.",
        )

    def test_retrieve_event_or_action_properties(self):
        self._create_taxonomy()
        toolkit = DummyToolkit(self.team, self.user)
        for item in ("event1", self.action.id):
            prompt = toolkit.retrieve_event_or_action_properties(item)
            self.assertIn("The data format is as follows:", prompt)
            self.assertIn("<Numeric>", prompt)
            self.assertIn("- id", prompt)
            self.assertIn("</Numeric>", prompt)
            self.assertIn("<String>", prompt)
            self.assertIn("- $browser – Name of the browser the user has used.", prompt)
            self.assertIn("</String>", prompt)
            self.assertIn("<DateTime>", prompt)
            self.assertIn("- date", prompt)
            self.assertIn("</DateTime>", prompt)
            self.assertIn("<Boolean>", prompt)
            self.assertIn("- bool", prompt)
            self.assertIn("</Boolean>", prompt)
            # Virtual properties are surfaced even though they never appear in stored event data.
            self.assertIn("- $virt_is_bot", prompt)

    def test_retrieve_event_or_action_property_values(self):
        self._create_taxonomy()
        toolkit = DummyToolkit(self.team, self.user)

        for item in ("event1", self.action.id):
            self.assertIn('"Chrome"', toolkit.retrieve_event_or_action_property_values(item, "$browser"))
            self.assertIn('"Firefox"', toolkit.retrieve_event_or_action_property_values(item, "$browser"))
            self.assertEqual(toolkit.retrieve_event_or_action_property_values(item, "bool"), "true")
            self.assertEqual(
                toolkit.retrieve_event_or_action_property_values(item, "id"),
                "9, 8, 7, 6, 5, 4, 3, 2, 1, 0",
            )
            self.assertEqual(
                toolkit.retrieve_event_or_action_property_values(item, "date"), f'"{datetime(2024, 1, 1).isoformat()}"'
            )

    @patch.object(DummyToolkit, "_retrieve_event_or_action_taxonomy")
    def test_retrieve_event_or_action_property_values_accepts_virtual_event_properties(self, mock_retrieve):
        toolkit = DummyToolkit(self.team, self.user)
        now = datetime(2024, 1, 1, tzinfo=UTC)
        mock_retrieve.return_value = (
            CachedEventTaxonomyQueryResponse(
                cache_key="virtual-event-property",
                is_cached=True,
                last_refresh=now,
                next_allowed_client_refresh=now,
                results=[],
                timezone="UTC",
            ),
            "event event1",
        )

        assert toolkit.retrieve_event_or_action_property_values("event1", "$virt_is_bot") == "true, false"

    def test_retrieve_event_or_action_properties_when_actions_exist_but_action_id_incorrect(self):
        toolkit = DummyToolkit(self.team, self.user)
        incorrect_action_id = self.action.id + 999  # Ensure it doesn't exist

        result = toolkit.retrieve_event_or_action_properties(incorrect_action_id)
        self.assertEqual(
            result,
            f"Action {incorrect_action_id} does not exist in the taxonomy. Verify that the action ID is correct and try again.",
        )

    def test_retrieve_event_or_action_properties_when_no_actions_exist_and_action_id_incorrect(self):
        Action.objects.all().delete()

        toolkit = DummyToolkit(self.team, self.user)
        incorrect_action_id = 9999

        result = toolkit.retrieve_event_or_action_properties(incorrect_action_id)
        self.assertEqual(result, "No actions exist in the project.")

    def test_enrich_props_with_descriptions(self):
        toolkit = DummyToolkit(self.team, self.user)
        res = toolkit._enrich_props_with_descriptions("event", [("$geoip_city_name", "String")])
        self.assertEqual(len(res), 1)
        prop, type, description = res[0]
        self.assertEqual(prop, "$geoip_city_name")
        self.assertEqual(type, "String")
        self.assertIsNotNone(description)

    def test_generate_properties_output_replaces_newlines_in_descriptions(self):
        toolkit = DummyToolkit(self.team, self.user)
        props: list[tuple[str, str | None, str | None]] = [
            ("test_prop", "String", "This is a description\nwith multiple\nlines")
        ]
        output = toolkit._generate_properties_output(props)
        self.assertIn("- test_prop – This is a description with multiple lines", output)
        self.assertNotIn("description\nwith", output)

    @patch("ee.hogai.chat_agent.query_planner.toolkit.restricted_property_names")
    def test_retrieve_entity_properties_excludes_restricted_properties(self, mock_restricted):
        mock_restricted.return_value = {"secret"}
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="secret", property_type="String"
        )
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="visible", property_type="String"
        )
        toolkit = DummyToolkit(self.team, self.user)
        result = toolkit.retrieve_entity_properties("person")
        self.assertIn("- visible", result)
        self.assertNotIn("- secret", result)

    @patch("ee.hogai.chat_agent.query_planner.toolkit.restricted_property_names")
    def test_retrieve_entity_property_values_hides_restricted_property(self, mock_restricted):
        mock_restricted.return_value = {"secret"}
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="secret", property_type="String"
        )
        toolkit = DummyToolkit(self.team, self.user)
        result = toolkit.retrieve_entity_property_values("person", "secret")
        self.assertIn("does not exist", result)

    @patch("ee.hogai.chat_agent.query_planner.toolkit.restricted_property_names")
    def test_retrieve_event_property_values_hides_restricted_property(self, mock_restricted):
        mock_restricted.return_value = {"$browser"}
        # The restriction guard short-circuits before any taxonomy query, so no stored data is needed.
        toolkit = DummyToolkit(self.team, self.user)
        result = toolkit.retrieve_event_or_action_property_values("event1", "$browser")
        self.assertIn("does not exist", result)


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
        tool = final_answer(query_kind="trends", plan=dedent(original))
        self.assertEqual(tool.plan.strip(), dedent(normalized).strip())
