from unittest.mock import patch

from ee.clickhouse.models.group import create_group
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.test.base import APIBaseTest

class ClickhouseTestGroupsApi(ClickhouseTestMixin, APIBaseTest):

    def test_property_values(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="org:1", properties={"industry": "finance"})
        group_type_index = 0
        key = "industry"
        response = self.client.get(f"/api/projects/{self.team.id}/groups/property_values/?key={key}&group_type_index={group_type_index}").json()
        self.assertEqual(len(response), 2)
        self.assertEqual(response[0]['name'][0], "finance")

    def test_property_definitions(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance", "name": "Mr. Krabs"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:1", properties={"name": "Plankton"})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:2", properties={})

        response = self.client.get(f"/api/projects/{self.team.id}/groups/property_definitions").json()
        self.assertEqual(response["0"][0]["name"], "industry")
        self.assertEqual(response["0"][0]["count"], 2)
        self.assertEqual(response["1"][0]["name"], "name")
        self.assertEqual(response["1"][0]["count"], 1)
