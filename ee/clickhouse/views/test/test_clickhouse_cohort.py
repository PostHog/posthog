import time
from unittest.mock import patch

from ee.clickhouse.client import sync_execute
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models import Person
from posthog.test.base import APIBaseTest


class ClickhouseTestCohorts(ClickhouseTestMixin, APIBaseTest):
    def test_creating_update_and_calculating(self):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(
            team=self.team, distinct_ids=["user_1"], properties={"$geoip_country_code": "HK", "organization_id": "zz"}
        )
        Person.objects.create(
            team=self.team, distinct_ids=["user_2"], properties={"$geoip_country_code": "HK", "organization_id": "xx"}
        )
        Person.objects.create(
            team=self.team, distinct_ids=["user_3"], properties={"$geoip_country_code": "HK", "organization_id": "xx"}
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["user_4"],
            properties={"$geoip_country_code": "HK", "organization_id": "xx", "a": "set"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["user_5"],
            properties={"$geoip_country_code": "HK", "organization_id": "xx", "a": "set"},
        )

        response = self.client.post(
            "/api/cohort",
            data={
                "name": "whatever",
                "groups": [
                    {
                        "properties": [
                            {"key": "$geoip_country_code", "type": "event", "value": ["HK"], "operator": "exact"},
                            {"key": "organization_id", "value": ["zz"], "operator": "exact", "type": "event"},
                        ]
                    }
                ],
            },
        )

        cohort_id = response.json()["id"]
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/cohort/{cohort_id}/",)
            time.sleep(1)

        print(response.json())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["is_calculating"], False)
        self.assertEqual(response.json()["count"], 1)

        response = self.client.patch(
            f"/api/cohort/{cohort_id}/",
            data={
                "name": "whatever",
                "groups": [
                    {
                        "properties": [
                            {"key": "$geoip_country_code", "type": "event", "value": ["HK"], "operator": "exact"},
                            {"key": "organization_id", "value": ["xx"], "operator": "exact", "type": "event"},
                        ]
                    }
                ],
            },
        )

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/cohort/{cohort_id}/",)
            time.sleep(0.5)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["name"], "whatever")
        self.assertEqual(response.json()["is_calculating"], False)
        self.assertEqual(response.json()["count"], 4)

        response = self.client.patch(
            f"/api/cohort/{cohort_id}/",
            data={
                "name": "whatever",
                "groups": [
                    {
                        "properties": [
                            {"key": "$geoip_country_code", "type": "event", "value": ["HK"], "operator": "exact"},
                            {"key": "organization_id", "value": ["xx"], "operator": "exact", "type": "event"},
                            {"key": "a", "type": "event", "value": "is_not_set", "operator": "is_not_set"},
                        ]
                    }
                ],
            },
        )

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/cohort/{cohort_id}/",)
            time.sleep(0.5)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["name"], "whatever")
        self.assertEqual(response.json()["is_calculating"], False)
        self.assertEqual(response.json()["count"], 2)

        with self.settings(SHELL_PLUS_PRINT_SQL=False):
            response = self.client.patch(
                f"/api/cohort/{cohort_id}/",
                data={
                    "name": "whatever",
                    "groups": [
                        {
                            "properties": [
                                {"key": "$geoip_country_code", "type": "event", "value": ["HK"], "operator": "exact"},
                                {"key": "organization_id", "value": ["xx"], "operator": "exact", "type": "event"},
                                {"key": "b", "type": "event", "value": "is_set", "operator": "is_set"},
                            ]
                        }
                    ],
                },
            )

            while response.json()["is_calculating"]:
                response = self.client.get(f"/api/cohort/{cohort_id}/",)
                time.sleep(0.5)

            print(response.json())
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["name"], "whatever")
            self.assertEqual(response.json()["is_calculating"], False)
            self.assertEqual(response.json()["count"], 0)
