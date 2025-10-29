from datetime import datetime

from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from posthog.models.group.util import raw_create_group_ch
from posthog.models.property_definition import PropertyDefinition
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit


class DummyToolkit(TaxonomyAgentToolkit):
    def get_tools(self):
        return self._get_default_tools()


class TestGroups(ClickhouseTestMixin, NonAtomicBaseTest):
    def setUp(self):
        super().setUp()
        for i, group_type in enumerate(["organization", "project", "no_properties"]):
            create_group_type_mapping_without_created_at(
                team=self.team, project_id=self.team.project_id, group_type_index=i, group_type=group_type
            )

        # Create property definitions for organization (group_type_index=0)
        PropertyDefinition.objects.create(
            team=self.team,
            name="name",
            property_type="String",
            is_numerical=False,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=0,  # organization
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="industry",
            property_type="String",
            is_numerical=False,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=0,  # organization
        )
        # Create property definitions for project (group_type_index=1)
        PropertyDefinition.objects.create(
            team=self.team,
            name="size",
            property_type="Numeric",
            is_numerical=True,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=1,  # project
        )
        PropertyDefinition.objects.create(
            team=self.team,
            name="name_group",
            property_type="String",
            is_numerical=False,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=0,
        )

        raw_create_group_ch(
            team_id=self.team.id,
            group_type_index=0,
            group_key="acme-corp",
            properties={"name": "Acme Corp", "industry": "tech"},
            created_at=datetime.now(),
            sync=True,  # Force sync to ClickHouse
        )
        raw_create_group_ch(
            team_id=self.team.id,
            group_type_index=1,
            group_key="acme-project",
            properties={"name": "Acme Project", "size": 100},
            created_at=datetime.now(),
            sync=True,  # Force sync to ClickHouse
        )

        self.toolkit = DummyToolkit(self.team, self.user)

    async def test_entity_names_with_existing_groups(self):
        # Test that the entity names include the groups we created in setUp
        result = await self.toolkit._get_entity_names()
        expected = ["person", "session", "organization", "project", "no_properties"]
        self.assertEqual(result, expected)

        property_vals = await self.toolkit.retrieve_entity_property_values(
            {"organization": ["name", "industry"], "project": ["size"]}
        )

        # Should return the actual values from the groups we created
        self.assertIn("organization", property_vals)
        self.assertIn("project", property_vals)

        self.assertTrue(any("Acme Corp" in str(val) for val in property_vals.get("organization", [])))
        self.assertTrue(any("tech" in str(val) for val in property_vals.get("organization", [])))
        self.assertTrue(any("100" in str(val) for val in property_vals.get("project", [])))

    async def test_retrieve_entity_property_values_wrong_group(self):
        property_vals = await self.toolkit.retrieve_entity_property_values(
            {"test": ["name", "industry"], "project": ["size"]}
        )

        self.assertIn("test", property_vals)
        self.assertIn(
            "Entity test not found. Available entities: person, session, organization, project, no_properties",
            property_vals["test"],
        )
        self.assertIn("project", property_vals)

    async def test_retrieve_entity_properties_group(self):
        result = await self.toolkit.retrieve_entity_properties_parallel(["organization"])

        assert (
            "<properties><String><prop><name>name</name></prop><prop><name>industry</name></prop><prop><name>name_group</name></prop></String></properties>"
            == result["organization"]
        )

    async def test_retrieve_entity_properties_group_not_found(self):
        result = await self.toolkit.retrieve_entity_properties_parallel(["test"])

        assert (
            "Entity test not found. Available entities: person, session, organization, project, no_properties"
            == result["test"]
        )

    async def test_retrieve_entity_properties_group_nothing_found(self):
        result = await self.toolkit.retrieve_entity_properties_parallel(["no_properties"])

        assert "Properties do not exist in the taxonomy for the entity no_properties." == result["no_properties"]

    async def test_retrieve_entity_properties_group_mixed(self):
        result = await self.toolkit.retrieve_entity_properties_parallel(["organization", "no_properties", "project"])

        assert "organization" in result
        assert "<properties>" in result["organization"]
        assert "Properties do not exist in the taxonomy for the entity no_properties." == result["no_properties"]
        assert "project" in result
        assert "<properties>" in result["project"]
