import json
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import Client
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Person
from posthog.models.cohort import Cohort
from posthog.test.base import APIBaseTest, _create_event, _create_person, flush_persons_and_events


class TestCohort(APIBaseTest):
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
                    "values": [{"type": "AND", "values": [{"key": "team_id", "value": 5, "type": "person"}]}],
                },
                "name_length": 8,
                "person_count_precalc": 0,
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
                    "values": [{"type": "AND", "values": [{"key": "team_id", "value": 6, "type": "person"}]}],
                },
                "name_length": 9,
                "person_count_precalc": 0,
                "groups_count": 1,
                "action_groups_count": 0,
                "properties_groups_count": 1,
                "deleted": False,
                "updated_by_creator": True,
            },
        )

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

        # Only change name without updating CSV
        response = client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}", {"name": "test2"}, format="multipart"
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
        person = Person.objects.create(team=self.team, properties={"email": "email@example.org"})
        person1 = Person.objects.create(team=self.team, distinct_ids=["123"])
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
            {"is_static": False, "groups": [{"properties": [{"key": "email", "value": "email@example.org"}]}]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(patch_calculate_cohort.call_count, 1)

    def test_cohort_list(self):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"prop": 5})
        Person.objects.create(team=self.team, properties={"prop": 6})

        self.client.post(
            f"/api/projects/{self.team.id}/cohorts", data={"name": "whatever", "groups": [{"properties": {"prop": 5}}]},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["name"], "whatever")
        self.assertEqual(response["results"][0]["created_by"]["id"], self.user.id)

    def test_csv_export(self):
        person1 = Person.objects.create(
            distinct_ids=["person1"], team_id=self.team.pk, properties={"$some_prop": "something"}
        )
        person2 = Person.objects.create(distinct_ids=["person2"], team_id=self.team.pk, properties={})
        person3 = Person.objects.create(
            distinct_ids=["person3"], team_id=self.team.pk, properties={"$some_prop": "something"}
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons.csv")
        self.assertEqual(len(response.content.splitlines()), 3, response.content)

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
                "groups": [{"properties": [{"type": "cohort", "value": response_a.json()["id"], "key": "id"}]}],
            },
        )
        self.assertEqual(patch_calculate_cohort.call_count, 2)

        # Cohort C that depends on Cohort B
        response_c = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort C",
                "groups": [{"properties": [{"type": "cohort", "value": response_b.json()["id"], "key": "id"}]}],
            },
        )
        self.assertEqual(patch_calculate_cohort.call_count, 3)

        # Update Cohort A to depend on Cohort C
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}",
            data={
                "name": "Cohort A, reloaded",
                "groups": [{"properties": [{"type": "cohort", "value": response_c.json()["id"], "key": "id"}]}],
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertDictContainsSubset(
            {"detail": "Cohorts cannot reference other cohorts in a loop.", "type": "validation_error"}, response.json()
        )
        self.assertEqual(patch_calculate_cohort.call_count, 3)

        # Update Cohort A to depend on Cohort A itself
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}",
            data={
                "name": "Cohort A, reloaded",
                "groups": [{"properties": [{"type": "cohort", "value": response_a.json()["id"], "key": "id"}]}],
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertDictContainsSubset(
            {"detail": "Cohorts cannot reference other cohorts in a loop.", "type": "validation_error"}, response.json()
        )
        self.assertEqual(patch_calculate_cohort.call_count, 3)

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
            {"detail": "Invalid Cohort ID in filter", "type": "validation_error"}, response.json()
        )
        self.assertEqual(patch_calculate_cohort.call_count, 1)

    @patch("posthog.api.cohort.report_user_action")
    def test_creating_update_and_calculating_with_new_cohort_filters(self, patch_capture):

        _create_person(distinct_ids=["p1"], team_id=self.team.pk, properties={"$some_prop": "something"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="p1", timestamp=datetime.now() - timedelta(hours=12)
        )

        _create_person(distinct_ids=["p2"], team_id=self.team.pk, properties={"$some_prop": "not it"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="p2", timestamp=datetime.now() - timedelta(hours=12)
        )

        _create_person(distinct_ids=["p3"], team_id=self.team.pk, properties={"$some_prop": "not it"})
        _create_event(
            team=self.team, event="$pageview", distinct_id="p3", timestamp=datetime.now() - timedelta(days=12)
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
                            {"key": "$some_prop", "value": "something", "type": "person"},
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
            data={"name": "whatever", "filters": "[Slkasd=lkxcn]", "groups": [{"properties": {"team_id": 5}}]},
        )

        self.assertEqual(update_response.status_code, 400, response.content)
        self.assertDictContainsSubset(
            {"detail": "Filters must be a dictionary with a 'properties' key.", "type": "validation_error"},
            update_response.json(),
        )

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_hard_delete_is_forbidden(self, patch_calculate_cohort, patch_capture):
        response_a = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort A", "groups": [{"properties": {"team_id": 5}}]},
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}",)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


def create_cohort(client: Client, team_id: int, name: str, groups: List[Dict[str, Any]]):
    return client.post(f"/api/projects/{team_id}/cohorts", {"name": name, "groups": json.dumps(groups)})


def create_cohort_ok(client: Client, team_id: int, name: str, groups: List[Dict[str, Any]]):
    response = create_cohort(client=client, team_id=team_id, name=name, groups=groups)
    assert response.status_code == 201, response.content
    return response.json()
