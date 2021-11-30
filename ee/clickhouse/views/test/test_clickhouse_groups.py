from datetime import datetime

from freezegun.api import freeze_time

from ee.clickhouse.models.group import create_group
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.test.base import APIBaseTest


class ClickhouseTestGroupsApi(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    @freeze_time("2021-05-02")
    def test_groups_list(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )
        create_group(
            team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"},
        )
        create_group(
            team_id=self.team.pk, group_type_index=1, group_key="company:1", properties={"name": "Plankton"},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0").json()
        self.assertEqual(
            response,
            {
                "next": None,
                "previous": None,
                "results": [
                    {
                        "created_at": "2021-05-02T00:00:00Z",
                        "group_key": "org:5",
                        "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                        "group_type_index": 0,
                    },
                    {
                        "created_at": "2021-05-02T00:00:00Z",
                        "group_key": "org:6",
                        "group_properties": {"industry": "technology"},
                        "group_type_index": 0,
                    },
                ],
            },
        )

    @freeze_time("2021-05-02")
    def test_retrieve_group(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="key",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )

        fail_response = self.client.get(f"/api/projects/{self.team.id}/groups/key?group_type_index=1")
        self.assertEqual(fail_response.status_code, 404)

        ok_response = self.client.get(f"/api/projects/{self.team.id}/groups/key?group_type_index=0")
        self.assertEqual(ok_response.status_code, 200)
        self.assertEqual(
            ok_response.json(),
            {
                "created_at": "2021-05-02T00:00:00Z",
                "group_key": "key",
                "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                "group_type_index": 0,
            },
        )

    def test_property_definitions(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:1", properties={"name": "Plankton"})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="company:2", properties={})

        response = self.client.get(f"/api/projects/{self.team.id}/groups/property_definitions").json()
        self.assertEqual(
            response,
            {
                "0": [{"name": "industry", "count": 2}, {"name": "name", "count": 1}],
                "1": [{"name": "name", "count": 1}],
            },
        )

    def test_property_values(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="org:1", properties={"industry": "finance"})
        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=industry&group_type_index=0"
        ).json()
        self.assertEqual(len(response), 2)
        self.assertEqual(response, [{"name": "finance"}, {"name": "technology"}])

    def test_empty_property_values(self):
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})
        create_group(team_id=self.team.pk, group_type_index=1, group_key="org:1", properties={"industry": "finance"})
        response = self.client.get(
            f"/api/projects/{self.team.id}/groups/property_values/?key=name&group_type_index=0"
        ).json()
        self.assertEqual(len(response), 0)
        self.assertEqual(response, [])
