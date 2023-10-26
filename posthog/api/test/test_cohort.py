import json
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import Client
from django.utils import timezone
from posthog.celery import clickhouse_clear_removed_data
from posthog.clickhouse.client.execute import sync_execute
from posthog.models.async_deletion.async_deletion import AsyncDeletion, DeletionType
from posthog.tasks.calculate_cohort import calculate_cohort_from_list
from rest_framework import status
from rest_framework.test import APIClient

from posthog.api.test.test_exports import TestExportMixin
from posthog.models import FeatureFlag, Person
from posthog.models.cohort import Cohort
from posthog.models.team.team import Team
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    QueryMatchingTest,
    snapshot_clickhouse_queries,
)


class TestCohort(TestExportMixin, ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    # select all queries for snapshots
    def capture_select_queries(self):
        return self.capture_queries(("INSERT INTO cohortpeople", "SELECT", "ALTER", "select", "DELETE"))

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_and_calculating(self, patch_calculate_cohort, patch_capture):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"team_id": 5})
        Person.objects.create(team=self.team, properties={"team_id": 6})

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)
        self.assertEqual(patch_calculate_cohort.call_count, 1)
        self.assertEqual(patch_capture.call_count, 1)

        # Assert analytics are sent
        patch_capture.assert_called_with(
            self.user,
            "cohort created",
            {
                "filters": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": "team_id", "value": 5, "type": "person"}],
                        }
                    ],
                },
                "name_length": 8,
                "groups_count": 1,
                "action_groups_count": 0,
                "properties_groups_count": 1,
                "deleted": False,
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
            data={
                "name": "whatever2",
                "description": "A great cohort!",
                "groups": [{"properties": {"team_id": 6}}],
                "created_by": "something something",
                "last_calculation": "some random date",
                "errors_calculating": 100,
                "deleted": False,
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertDictContainsSubset({"name": "whatever2", "description": "A great cohort!"}, response.json())
        self.assertEqual(patch_calculate_cohort.call_count, 2)

        # Assert analytics are sent
        patch_capture.assert_called_with(
            self.user,
            "cohort updated",
            {
                "filters": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": "team_id", "value": 6, "type": "person"}],
                        }
                    ],
                },
                "name_length": 9,
                "groups_count": 1,
                "action_groups_count": 0,
                "properties_groups_count": 1,
                "deleted": False,
                "updated_by_creator": True,
            },
        )

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_list_cohorts_is_not_nplus1(self, patch_calculate_cohort, patch_capture):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"team_id": 5})
        Person.objects.create(team=self.team, properties={"team_id": 6})

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(response.status_code, 201, response.content)

        with self.assertNumQueries(8):
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts")
            assert len(response.json()["results"]) == 1

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(response.status_code, 201, response.content)

        with self.assertNumQueries(8):
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts")
            assert len(response.json()["results"]) == 2

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload(self, patch_calculate_cohort_from_list):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"email": "email@example.org"})
        Person.objects.create(team=self.team, distinct_ids=["123"])
        Person.objects.create(team=self.team, distinct_ids=["456"])

        csv = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID,
email@example.org,
123
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test", "csv": csv, "is_static": True},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        self.assertFalse(response.json()["is_calculating"], False)
        self.assertFalse(Cohort.objects.get(pk=response.json()["id"]).is_calculating)

        calculate_cohort_from_list(response.json()["id"], ["email@example.org", "123"])
        self.assertEqual(Cohort.objects.get(pk=response.json()["id"]).count, 1)

        csv = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID,
456
"""
            ),
            content_type="application/csv",
        )

        #  A weird issue with pytest client, need to user Rest framework's one
        #  see https://stackoverflow.com/questions/39906956/patch-and-put-dont-work-as-expected-when-pytest-is-interacting-with-rest-framew
        client = APIClient()
        client.force_login(self.user)
        response = client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
            {"name": "test", "csv": csv},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 2)
        self.assertFalse(response.json()["is_calculating"], False)
        self.assertFalse(Cohort.objects.get(pk=response.json()["id"]).is_calculating)

        calculate_cohort_from_list(response.json()["id"], ["456"])
        self.assertEqual(Cohort.objects.get(pk=response.json()["id"]).count, 2)

        # Only change name without updating CSV
        response = client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
            {"name": "test2"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 2)
        self.assertFalse(response.json()["is_calculating"], False)
        self.assertFalse(Cohort.objects.get(pk=response.json()["id"]).is_calculating)
        self.assertEqual(Cohort.objects.get(pk=response.json()["id"]).name, "test2")

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_static_cohort_to_dynamic_cohort(self, patch_calculate_cohort, patch_calculate_cohort_from_list):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"email": "email@example.org"})
        Person.objects.create(team=self.team, distinct_ids=["123"])
        Person.objects.create(team=self.team, distinct_ids=["456"])

        csv = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID,
email@example.org,
123
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test", "csv": csv, "is_static": True},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        self.assertFalse(response.json()["is_calculating"], False)
        self.assertFalse(Cohort.objects.get(pk=response.json()["id"]).is_calculating)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
            {
                "is_static": False,
                "groups": [{"properties": [{"key": "email", "value": "email@example.org"}]}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_calculate_cohort.call_count, 1)

    def test_cohort_list(self):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"prop": 5})
        Person.objects.create(team=self.team, properties={"prop": 6})

        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"prop": 5}}]},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["name"], "whatever")
        self.assertEqual(response["results"][0]["created_by"]["id"], self.user.id)

    def test_csv_export_new(self):
        # Test 100s of distinct_ids, we only want ~10
        Person.objects.create(
            distinct_ids=["person3"] + [f"person_{i}" for i in range(4, 100)],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        Person.objects.create(
            distinct_ids=["person1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something", "email": "test@test.com"},
        )
        Person.objects.create(distinct_ids=["person2"], team_id=self.team.pk, properties={})
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        cohort.calculate_people_ch(pending_version=0)

        lines = self._get_export_output(f"/api/cohort/{cohort.pk}/persons")
        headers = lines[0].split(",")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[1].split(",")[headers.index("email")], "test@test.com")
        self.assertEqual(lines[0].count("distinct_id"), 10)

    def test_filter_by_cohort(self):
        _create_person(team=self.team, distinct_ids=[f"fake"], properties={})
        for i in range(150):
            _create_person(
                team=self.team,
                distinct_ids=[f"person_{i}"],
                properties={"$os": "Chrome"},
            )

        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 100, response)

        response = self.client.get(response.json()["next"])
        self.assertEqual(len(response.json()["results"]), 50, response)

    def test_filter_by_cohort_prop(self):
        for i in range(5):
            _create_person(
                team=self.team,
                distinct_ids=[f"person_{i}"],
                properties={"$os": "Chrome"},
            )

        _create_person(
            team=self.team,
            distinct_ids=[f"target"],
            properties={"$os": "Chrome", "$browser": "Safari"},
        )

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self.client.get(
            f"/api/cohort/{cohort.pk}/persons?properties=%s"
            % (json.dumps([{"key": "$browser", "value": "Safari", "type": "person"}]))
        )
        self.assertEqual(len(response.json()["results"]), 1, response)

    # TODO: Remove this when load-person-field-from-clickhouse feature flag is removed
    @patch("posthog.api.person.posthoganalytics.feature_enabled", return_value=True)
    def test_filter_by_cohort_prop_from_clickhouse(self, patch_feature_enabled):
        for i in range(5):
            _create_person(
                team=self.team,
                distinct_ids=[f"person_{i}"],
                properties={"$os": "Chrome"},
            )

        _create_person(
            team=self.team,
            distinct_ids=[f"target"],
            properties={"$os": "Chrome", "$browser": "Safari"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"not_target"],
            properties={"$os": "Something else", "$browser": "Safari"},
        )

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self.client.get(
            f"/api/cohort/{cohort.pk}/persons?properties=%s"
            % (json.dumps([{"key": "$browser", "value": "Safari", "type": "person"}]))
        )
        self.assertEqual(len(response.json()["results"]), 1, response)

    def test_filter_by_cohort_search(self):
        for i in range(5):
            _create_person(
                team=self.team,
                distinct_ids=[f"person_{i}"],
                properties={"$os": "Chrome"},
            )

        _create_person(
            team=self.team,
            distinct_ids=[f"target"],
            properties={"$os": "Chrome", "$browser": "Safari"},
        )
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons?search=target")
        self.assertEqual(len(response.json()["results"]), 1, response)

    def test_filter_by_static_cohort(self):
        Person.objects.create(team_id=self.team.pk, distinct_ids=["1"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["123"])
        Person.objects.create(team_id=self.team.pk, distinct_ids=["2"])
        # Team leakage
        team2 = Team.objects.create(organization=self.organization)
        Person.objects.create(team=team2, distinct_ids=["1"])

        cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True, last_calculation=timezone.now())
        cohort.insert_users_by_list(["1", "123"])

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 2, response)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_and_calculating_with_cycle(self, patch_calculate_cohort, patch_capture):
        # Cohort A
        response_a = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort A", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(patch_calculate_cohort.call_count, 1)

        # Cohort B that depends on Cohort A
        response_b = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort B",
                "groups": [
                    {
                        "properties": [
                            {
                                "type": "cohort",
                                "value": response_a.json()["id"],
                                "key": "id",
                            }
                        ]
                    }
                ],
            },
        )
        self.assertEqual(patch_calculate_cohort.call_count, 2)

        # Cohort C that depends on Cohort B
        response_c = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort C",
                "groups": [
                    {
                        "properties": [
                            {
                                "type": "cohort",
                                "value": response_b.json()["id"],
                                "key": "id",
                            }
                        ]
                    }
                ],
            },
        )
        self.assertEqual(patch_calculate_cohort.call_count, 3)

        # Update Cohort A to depend on Cohort C
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}",
            data={
                "name": "Cohort A, reloaded",
                "groups": [
                    {
                        "properties": [
                            {
                                "type": "cohort",
                                "value": response_c.json()["id"],
                                "key": "id",
                            }
                        ]
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertDictContainsSubset(
            {
                "detail": "Cohorts cannot reference other cohorts in a loop.",
                "type": "validation_error",
            },
            response.json(),
        )
        self.assertEqual(patch_calculate_cohort.call_count, 3)

        # Update Cohort A to depend on Cohort A itself
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}",
            data={
                "name": "Cohort A, reloaded",
                "groups": [
                    {
                        "properties": [
                            {
                                "type": "cohort",
                                "value": response_a.json()["id"],
                                "key": "id",
                            }
                        ]
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertDictContainsSubset(
            {
                "detail": "Cohorts cannot reference other cohorts in a loop.",
                "type": "validation_error",
            },
            response.json(),
        )
        self.assertEqual(patch_calculate_cohort.call_count, 3)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_with_non_directed_cycle(self, patch_calculate_cohort, patch_capture):
        # Cohort A
        response_a = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort A", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(patch_calculate_cohort.call_count, 1)

        # Cohort B that depends on Cohort A
        response_b = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort B",
                "groups": [
                    {
                        "properties": [
                            {
                                "type": "cohort",
                                "value": response_a.json()["id"],
                                "key": "id",
                            }
                        ]
                    }
                ],
            },
        )
        self.assertEqual(patch_calculate_cohort.call_count, 2)

        # Cohort C that depends on both Cohort A & B
        response_c = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort C",
                "groups": [
                    {
                        "properties": [
                            {
                                "type": "cohort",
                                "value": response_b.json()["id"],
                                "key": "id",
                            },
                            {
                                "type": "cohort",
                                "value": response_a.json()["id"],
                                "key": "id",
                            },
                        ]
                    }
                ],
            },
        )
        self.assertEqual(patch_calculate_cohort.call_count, 3)

        # Update Cohort C
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_c.json()['id']}",
            data={
                "name": "Cohort C, reloaded",
            },
        )
        # it's not a loop because C depends on A & B, B depends on A, and A depends on nothing.
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(patch_calculate_cohort.call_count, 4)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_and_calculating_with_invalid_cohort(self, patch_calculate_cohort, patch_capture):
        # Cohort A
        response_a = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort A", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(patch_calculate_cohort.call_count, 1)

        # Update Cohort A to depend on an invalid cohort
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}",
            data={
                "name": "Cohort A, reloaded",
                "groups": [{"properties": [{"type": "cohort", "value": "99999", "key": "id"}]}],
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertDictContainsSubset(
            {"detail": "Invalid Cohort ID in filter", "type": "validation_error"},
            response.json(),
        )
        self.assertEqual(patch_calculate_cohort.call_count, 1)

    @patch("posthog.api.cohort.report_user_action")
    def test_creating_update_and_calculating_with_new_cohort_filters(self, patch_capture):
        _create_person(
            distinct_ids=["p1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p2"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p3"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=12),
        )

        flush_persons_and_events()

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                            {
                                "key": "$pageview",
                                "event_type": "events",
                                "time_value": 1,
                                "time_interval": "day",
                                "value": "performed_event",
                                "type": "behavioral",
                            },
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        cohort_id = response.json()["id"]

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(2, len(response.json()["results"]))

    @patch("posthog.api.cohort.report_user_action")
    def test_cohort_with_is_set_filter_missing_value(self, patch_capture):
        # regression test: Removing `value` was silently failing

        _create_person(
            distinct_ids=["p1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_person(
            distinct_ids=["p2"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_person(
            distinct_ids=["p3"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_person(distinct_ids=["p4"], team_id=self.team.pk, properties={})
        flush_persons_and_events()

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "type": "person",
                                "operator": "is_set",
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        cohort_id = response.json()["id"]

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(3, len(response.json()["results"]))

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_and_calculating_ignore_bad_filters(self, patch_calculate_cohort, patch_capture):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"team_id": 5})
        Person.objects.create(team=self.team, properties={"team_id": 6})

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
        )

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
            data={
                "name": "whatever",
                "filters": "[Slkasd=lkxcn]",
                "groups": [{"properties": {"team_id": 5}}],
            },
        )

        self.assertEqual(update_response.status_code, 400, response.content)
        self.assertDictContainsSubset(
            {
                "detail": "Filters must be a dictionary with a 'properties' key.",
                "type": "validation_error",
            },
            update_response.json(),
        )

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_hard_delete_is_forbidden(self, patch_calculate_cohort, patch_capture):
        response_a = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort A", "groups": [{"properties": {"team_id": 5}}]},
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_update_cohort_used_in_flags(self, patch_calculate_cohort, patch_capture):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                        ],
                    }
                },
            },
        )

        cohort_pk = response.json()["id"]

        second_cohort_pk = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort XX",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "event_type": "events",
                                "time_value": 1,
                                "time_interval": "day",
                                "value": "performed_event",
                                "type": "behavioral",
                            },
                        ],
                    }
                },
            },
        ).json()["id"]

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort_pk, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_pk}",
            data={
                "name": "cohort A",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                            {
                                "key": "$pageview",
                                "event_type": "events",
                                "time_value": 1,
                                "time_interval": "day",
                                "value": "performed_event",
                                "type": "behavioral",
                            },
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Behavioral filters cannot be added to cohorts used in feature flags.",
                "attr": "filters",
            },
            response.json(),
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_pk}",
            data={
                "name": "cohort C",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                            {
                                "key": "id",
                                "value": second_cohort_pk,
                                "type": "cohort",
                            },
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertDictContainsSubset(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "A dependent cohort (cohort XX) has filters based on events. These cohorts can't be used in feature flags.",
                "attr": "filters",
            },
            response.json(),
        )

    @patch("posthog.api.cohort.report_user_action")
    def test_duplicating_dynamic_cohort_as_static(self, patch_capture):
        _create_person(
            distinct_ids=["p1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p2"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p3"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=12),
        )

        flush_persons_and_events()

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                            {
                                "key": "$pageview",
                                "event_type": "events",
                                "time_value": 1,
                                "time_interval": "day",
                                "value": "performed_event",
                                "type": "behavioral",
                            },
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        cohort_id = response.json()["id"]

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/duplicate_as_static_cohort")
        self.assertEqual(response.status_code, 200, response.content)

        new_cohort_id = response.json()["id"]
        new_cohort = Cohort.objects.get(pk=new_cohort_id)
        self.assertEqual(new_cohort.is_static, True)

        while new_cohort.is_calculating:
            new_cohort.refresh_from_db()
            import time

            time.sleep(0.1)
        self.assertEqual(new_cohort.name, "cohort A (static copy)")
        self.assertEqual(new_cohort.is_calculating, False)
        self.assertEqual(new_cohort.errors_calculating, 0)
        self.assertEqual(new_cohort.count, 2)

    @snapshot_clickhouse_queries
    @patch("posthog.api.cohort.report_user_action")
    def test_async_deletion_of_cohort(self, patch_capture):
        _create_person(
            distinct_ids=["p1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p2"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p3"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=12),
        )

        flush_persons_and_events()

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                            {
                                "key": "$pageview",
                                "event_type": "events",
                                "time_value": 1,
                                "time_interval": "day",
                                "value": "performed_event",
                                "type": "behavioral",
                            },
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        cohort_id = response.json()["id"]

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")

        cohort = Cohort.objects.get(pk=cohort_id)
        self.assertEqual(cohort.count, 2)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                        ],
                    }
                },
            },
        )

        self.assertEqual(response.status_code, 200, response.content)

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")

        updated_cohort = Cohort.objects.get(pk=cohort_id)
        self.assertEqual(updated_cohort.count, 1)

        self.assertEqual(len(AsyncDeletion.objects.all()), 1)
        async_deletion = AsyncDeletion.objects.all()[0]
        self.assertEqual(async_deletion.key, f"{cohort_id}_2")
        self.assertEqual(async_deletion.deletion_type, DeletionType.Cohort_stale)
        self.assertEqual(async_deletion.delete_verified_at, None)

        # now let's run async deletions
        clickhouse_clear_removed_data.delay()

        async_deletion = AsyncDeletion.objects.all()[0]
        self.assertEqual(async_deletion.key, f"{cohort_id}_2")
        self.assertEqual(async_deletion.deletion_type, DeletionType.Cohort_stale)
        self.assertEqual(async_deletion.delete_verified_at, None)

        # optimise cohortpeople table, so all collapsing / replcaing on the merge tree is done
        sync_execute(f"OPTIMIZE TABLE cohortpeople FINAL SETTINGS mutations_sync = 2")

        # check clickhouse data is gone from cohortpeople table
        res = sync_execute(
            "SELECT count() FROM cohortpeople WHERE cohort_id = %(cohort_id)s",
            {"cohort_id": cohort_id},
        )
        self.assertEqual(res[0][0], 1)

        # now let's ensure verification of deletion happens on next run
        clickhouse_clear_removed_data.delay()

        async_deletion = AsyncDeletion.objects.all()[0]
        self.assertEqual(async_deletion.key, f"{cohort_id}_2")
        self.assertEqual(async_deletion.deletion_type, DeletionType.Cohort_stale)
        self.assertEqual(async_deletion.delete_verified_at is not None, True)

    def test_deletion_of_cohort_cancels_async_deletion(self):
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.pk}",
            data={
                "deleted": True,
            },
        )

        self.assertEqual(len(AsyncDeletion.objects.all()), 1)

        self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.pk}",
            data={
                "deleted": False,
            },
        )

        self.assertEqual(len(AsyncDeletion.objects.all()), 0)

    @patch("posthog.api.cohort.report_user_action")
    def test_async_deletion_of_cohort_with_race_condition_multiple_updates(self, patch_capture):
        _create_person(
            distinct_ids=["p1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p2"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p3"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            timestamp=datetime.now() - timedelta(days=12),
        )

        flush_persons_and_events()

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                            {
                                "key": "$pageview",
                                "event_type": "events",
                                "time_value": 1,
                                "time_interval": "day",
                                "value": "performed_event",
                                "type": "behavioral",
                            },
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        cohort_id = response.json()["id"]

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")

        cohort = Cohort.objects.get(pk=cohort_id)
        self.assertEqual(cohort.count, 2)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.content)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something2",
                                "type": "person",
                            },
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.content)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {"key": "$some_prop", "value": "not it", "type": "person"},
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.content)

        self.assertEqual(len(AsyncDeletion.objects.all()), 3)
        async_deletion_keys = {async_del.key for async_del in AsyncDeletion.objects.all()}
        async_deletion_type = {async_del.deletion_type for async_del in AsyncDeletion.objects.all()}
        self.assertEqual(async_deletion_keys, {f"{cohort_id}_2", f"{cohort_id}_3", f"{cohort_id}_4"})
        self.assertEqual(async_deletion_type - {DeletionType.Cohort_stale}, set())

        # now let's run async deletions
        clickhouse_clear_removed_data.delay()

        async_deletion = AsyncDeletion.objects.all()[0]
        self.assertEqual(async_deletion.key, f"{cohort_id}_2")
        self.assertEqual(async_deletion.deletion_type, DeletionType.Cohort_stale)
        self.assertEqual(async_deletion.delete_verified_at, None)

        # optimise cohortpeople table, so all collapsing / replcaing on the merge tree is done
        sync_execute(f"OPTIMIZE TABLE cohortpeople FINAL SETTINGS mutations_sync = 2")

        # check clickhouse data is gone from cohortpeople table
        # Without async deletions, this number would've been 5, because of extra random stuff being added to cohortpeople table
        # due to the racy calls to update cohort
        res = sync_execute(
            "SELECT count() FROM cohortpeople WHERE cohort_id = %(cohort_id)s",
            {"cohort_id": cohort_id},
        )
        self.assertEqual(res[0][0], 2)

        # now let's ensure verification of deletion happens on next run
        clickhouse_clear_removed_data.delay()

        async_deletion = AsyncDeletion.objects.all()[0]
        self.assertEqual(async_deletion.key, f"{cohort_id}_2")
        self.assertEqual(async_deletion.deletion_type, DeletionType.Cohort_stale)
        self.assertEqual(async_deletion.delete_verified_at is not None, True)


def create_cohort(client: Client, team_id: int, name: str, groups: List[Dict[str, Any]]):
    return client.post(f"/api/projects/{team_id}/cohorts", {"name": name, "groups": json.dumps(groups)})


def create_cohort_ok(client: Client, team_id: int, name: str, groups: List[Dict[str, Any]]):
    response = create_cohort(client=client, team_id=team_id, name=name, groups=groups)
    assert response.status_code == 201, response.content
    return response.json()
