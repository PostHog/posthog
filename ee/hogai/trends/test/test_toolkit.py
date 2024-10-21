from django.test import override_settings
from freezegun import freeze_time

from ee.hogai.trends.toolkit import TrendsAgentToolkit
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
)


@override_settings(IN_UNIT_TESTING=True)
class TestToolkit(ClickhouseTestMixin, APIBaseTest):
    def test_retrieve_entity_properties(self):
        toolkit = TrendsAgentToolkit(self.team)

        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="test", property_type="String"
        )
        self.assertEqual(
            toolkit.retrieve_entity_properties("person"),
            "<properties><String><name>test</name><br /></String></properties>",
        )

        GroupTypeMapping.objects.create(team=self.team, group_type_index=0, group_type="group")
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.GROUP, group_type_index=0, name="test", property_type="Numeric"
        )
        self.assertEqual(
            toolkit.retrieve_entity_properties("group"),
            "<properties><Numeric><name>test</name><br /></Numeric></properties>",
        )

        self.assertNotEqual(
            toolkit.retrieve_entity_properties("session"),
            "<properties />",
        )
        self.assertIn(
            "$session_duration",
            toolkit.retrieve_entity_properties("session"),
        )

    def test_retrieve_entity_property_values(self):
        toolkit = TrendsAgentToolkit(self.team)
        self.assertEqual(
            toolkit.retrieve_entity_property_values("session", "$session_duration"),
            "30, 146, 2 and many more distinct values.",
        )
        self.assertEqual(
            toolkit.retrieve_entity_property_values("session", "nonsense"),
            "The property nonsense does not exist in the taxonomy.",
        )

        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="email", property_type=PropertyType.String
        )
        PropertyDefinition.objects.create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="id", property_type=PropertyType.Numeric
        )

        for i in range(5):
            id = f"person{i}"
            with freeze_time(f"2024-01-01T{i}:00:00Z"):
                _create_person(
                    distinct_ids=[id],
                    properties={"email": f"{id}@example.com", "id": i},
                    team=self.team,
                )
        with freeze_time(f"2024-01-02T00:00:00Z"):
            _create_person(
                distinct_ids=["person5"],
                properties={"email": "person5@example.com", "id": 5},
                team=self.team,
            )

        self.assertEqual(
            toolkit.retrieve_entity_property_values("person", "email"),
            '"person5@example.com", "person4@example.com", "person3@example.com", "person2@example.com", "person1@example.com" and 1 more distinct value.',
        )
        self.assertEqual(
            toolkit.retrieve_entity_property_values("person", "id"),
            "5, 4, 3, 2, 1 and 1 more distinct value.",
        )

        toolkit = TrendsAgentToolkit(self.team)
        GroupTypeMapping.objects.create(team=self.team, group_type_index=0, group_type="proj")
        GroupTypeMapping.objects.create(team=self.team, group_type_index=1, group_type="org")
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
            "6, 5, 4, 3, 2 and 2 more distinct values.",
        )
        self.assertEqual(toolkit.retrieve_entity_property_values("org", "test"), '"7"')

    def test_group_names(self):
        GroupTypeMapping.objects.create(team=self.team, group_type_index=0, group_type="proj")
        GroupTypeMapping.objects.create(team=self.team, group_type_index=1, group_type="org")
        toolkit = TrendsAgentToolkit(self.team)
        self.assertEqual(toolkit._entity_names, ["person", "session", "proj", "org"])
