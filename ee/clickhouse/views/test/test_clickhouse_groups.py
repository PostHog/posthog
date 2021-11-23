from datetime import datetime

from ee.clickhouse.models.group import create_group
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.test.base import APIBaseTest


class ClickhouseTestGroupsApi(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def test_groups_list(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:5",
            properties={"industry": "finance", "name": "Mr. Krabs"},
            timestamp=datetime(2021, 5, 2),
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:6",
            properties={"industry": "technology"},
            timestamp=datetime(2021, 5, 3),
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="company:1",
            properties={"name": "Plankton"},
            timestamp=datetime(2021, 5, 4),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0").json()
        self.assertEqual(
            response,
            {
                "next_url": None,
                "previous_url": None,
                "results": [
                    {
                        "created_at": "2021-05-02T00:00:00",
                        "group_key": "org:5",
                        "group_properties": {"industry": "finance", "name": "Mr. Krabs"},
                        "group_type_index": 0,
                    },
                    {
                        "created_at": "2021-05-03T00:00:00",
                        "group_key": "org:6",
                        "group_properties": {"industry": "technology"},
                        "group_type_index": 0,
                    },
                ],
            },
        )

    def test_groups_list_pagination(self):
        for i in range(5):
            create_group(
                team_id=self.team.pk, group_type_index=0, group_key=f"org:{i}", properties={},
            )

        response = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&limit=2").json()
        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(response["previous_url"], None)
        self.assertEqual(
            response["next_url"],
            f"http://testserver/api/projects/{self.team.id}/groups?group_type_index=0&limit=2&offset=2",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&limit=2&offset=2").json()
        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(
            response["previous_url"], f"api/projects/{self.team.id}/groups?group_type_index=0&limit=2&offset=0"
        )
        self.assertEqual(
            response["next_url"], f"api/projects/{self.team.id}/groups?group_type_index=0&limit=2&offset=4"
        )

        response = self.client.get(f"/api/projects/{self.team.id}/groups?group_type_index=0&limit=2&offset=4").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(
            response["previous_url"], f"api/projects/{self.team.id}/groups?group_type_index=0&limit=2&offset=2"
        )
        self.assertEqual(response["next_url"], None)

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
