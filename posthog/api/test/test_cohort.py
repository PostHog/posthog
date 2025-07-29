import json
from ee.clickhouse.materialized_columns.analyze import materialize
from datetime import datetime, timedelta
from typing import Optional, Any
from unittest import mock
from unittest.mock import patch, MagicMock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import Client
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from posthog.api.test.test_exports import TestExportMixin
from posthog.clickhouse.client.execute import sync_execute
from posthog.models import FeatureFlag, Person, Action
from posthog.models.async_deletion.async_deletion import AsyncDeletion
from posthog.models.cohort import Cohort
from posthog.models.team.team import Team
from posthog.schema import PropertyOperator, PersonsOnEventsMode
from posthog.tasks.calculate_cohort import (
    calculate_cohort_ch,
    calculate_cohort_from_list,
    get_cohort_calculation_candidates_queryset,
    increment_version_and_enqueue_calculate_cohort,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_person,
    flush_persons_and_events,
)


class TestCohort(TestExportMixin, ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    # select all queries for snapshots
    def capture_select_queries(self):
        return self.capture_queries_startswith(("INSERT INTO cohortpeople", "SELECT", "ALTER", "select", "DELETE"))

    def _get_cohort_activity(
        self,
        flag_id: Optional[int] = None,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ):
        if team_id is None:
            team_id = self.team.id

        if flag_id:
            url = f"/api/projects/{team_id}/cohorts/{flag_id}/activity"
        else:
            url = f"/api/projects/{team_id}/cohorts/activity"

        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def assert_cohort_activity(self, cohort_id: Optional[int], expected: list[dict]):
        activity_response = self._get_cohort_activity(cohort_id)

        activity: list[dict] = activity_response["results"]
        self.maxDiff = None

        # Sort 'changes' lists for order-insensitive comparison
        for item in activity:
            if "detail" in item and "changes" in item["detail"]:
                item["detail"]["changes"].sort(key=lambda x: x.get("field", ""))
        for item in expected:
            if "detail" in item and "changes" in item["detail"]:
                item["detail"]["changes"].sort(key=lambda x: x.get("field", ""))

        assert activity == expected

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_increment_cohort(self, mock_calculate_cohort_ch):
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
            pending_version=None,
            is_static=False,
            is_calculating=False,
            deleted=False,
        )

        assert cohort1 in get_cohort_calculation_candidates_queryset()

        increment_version_and_enqueue_calculate_cohort(cohort1, initiating_user=None)
        cohort1.refresh_from_db()
        assert cohort1.pending_version == 1
        assert cohort1.is_calculating is True
        assert cohort1 not in get_cohort_calculation_candidates_queryset()

        increment_version_and_enqueue_calculate_cohort(cohort1, initiating_user=None)
        cohort1.refresh_from_db()
        assert cohort1.pending_version == 2
        assert cohort1.is_calculating is True
        assert cohort1 not in get_cohort_calculation_candidates_queryset()

        increment_version_and_enqueue_calculate_cohort(cohort1, initiating_user=None)
        cohort1.refresh_from_db()
        assert cohort1.pending_version == 3
        assert cohort1.is_calculating is True
        assert cohort1 not in get_cohort_calculation_candidates_queryset()

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay", side_effect=calculate_cohort_ch)
    @patch("posthog.models.cohort.util.sync_execute", side_effect=sync_execute)
    def test_creating_update_and_calculating(self, patch_sync_execute, patch_calculate_cohort, patch_capture):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"team_id": 5})
        Person.objects.create(team=self.team, properties={"team_id": 6})

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"team_id": "5"}}]},
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
                            "values": [{"key": "team_id", "value": "5", "type": "person"}],
                        }
                    ],
                },
                "name_length": 8,
                "deleted": False,
            },
        )

        with self.capture_queries_startswith("INSERT INTO cohortpeople") as insert_statements:
            response = self.client.patch(
                f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
                data={
                    "name": "whatever2",
                    "description": "A great cohort!",
                    "groups": [{"properties": {"team_id": "6"}}],
                    "created_by": "something something",
                    "last_calculation": "some random date",
                    "errors_calculating": 100,
                    "deleted": False,
                },
            )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertDictContainsSubset({"name": "whatever2", "description": "A great cohort!"}, response.json())
            self.assertEqual(patch_calculate_cohort.call_count, 2)

            self.assertIn(f" user_id:{self.user.id} ", insert_statements[0])

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
                            "values": [{"key": "team_id", "value": "6", "type": "person"}],
                        }
                    ],
                },
                "name_length": 9,
                "deleted": False,
                "updated_by_creator": True,
            },
        )

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay", side_effect=calculate_cohort_ch)
    @patch("posthog.models.cohort.util.sync_execute", side_effect=sync_execute)
    def test_action_persons_on_events(self, patch_sync_execute, patch_calculate_cohort, patch_capture):
        materialize("person", "favorite_number", table_column="properties")
        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS}
        self.team.save()
        _create_person(
            team=self.team,
            distinct_ids=[f"person_1"],
            properties={"favorite_number": 5},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person_2"],
            properties={"favorite_number": 6},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person_1",
            timestamp=datetime.now() - timedelta(hours=12),
        )
        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {
                    "event": "$pageview",
                    "properties": [{"key": "favorite_number", "type": "person", "value": "5"}],
                }
            ],
        )

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "whatever",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": action.pk,
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "negation": False,
                                        "event_type": "actions",
                                        "time_value": 30,
                                        "time_interval": "day",
                                        "explicit_datetime": "-30d",
                                    }
                                ],
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)
        self.assertEqual(patch_calculate_cohort.call_count, 1)
        self.assertEqual(patch_capture.call_count, 1)

        with self.capture_queries_startswith("INSERT INTO cohortpeople") as insert_statements:
            response = self.client.patch(
                f"/api/projects/{self.team.id}/cohorts/{response.json()['id']}",
                data={
                    "name": "whatever2",
                    "description": "A great cohort!",
                    "groups": [{"properties": {"favorite_number": 6}}],
                    "created_by": "something something",
                    "last_calculation": "some random date",
                    "errors_calculating": 100,
                    "deleted": False,
                },
            )

            # Assert that the cohort calculation uses the materialized column
            # on the person table.
            self.assertIn(f"person.pmat_favorite_number", insert_statements[0])

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

        with self.assertNumQueries(12):
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts")
            assert len(response.json()["results"]) == 1

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(response.status_code, 201, response.content)
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(response.status_code, 201, response.content)

        with self.assertNumQueries(12):
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts")
            assert len(response.json()["results"]) == 3

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

        #  A weird issue with pytest client, need to user Rest framework's one
        #  see https://stackoverflow.com/questions/39906956/patch-and-put-dont-work-as-expected-when-pytest-is-interacting-with-rest-framew
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

    def test_cohort_list_with_search(self):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()

        Person.objects.create(team=self.team, properties={"prop": 5})
        Person.objects.create(team=self.team, properties={"prop": 6})

        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort1", "groups": [{"properties": {"prop": 5}}]},
        )

        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort2", "groups": [{"properties": {"prop": 6}}]},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts").json()
        self.assertEqual(len(response["results"]), 2)

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?search=cohort1").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["name"], "cohort1")

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?search=nomatch").json()
        self.assertEqual(len(response["results"]), 0)

    @patch("posthog.api.cohort.report_user_action")
    def test_list_cohorts_excludes_behavioral_cohorts(self, patch_capture):
        # Create a regular cohort
        regular_cohort = Cohort.objects.create(
            team=self.team,
            name="regular cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "person", "key": "email", "value": "test@posthog.com"}],
                }
            },
        )

        # Create a behavioral cohort
        Cohort.objects.create(
            team=self.team,
            name="behavioral cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "type": "behavioral",
                                    "key": "$pageview",
                                    "value": "performed_event",
                                    "event_type": "events",
                                    "time_value": 30,
                                    "time_interval": "day",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Test without filter
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

        # Test with behavioral filter
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?hide_behavioral_cohorts=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], regular_cohort.id)

    @patch("posthog.api.cohort.report_user_action")
    def test_list_cohorts_excludes_nested_behavioral_cohorts(self, patch_capture):
        # Create a behavioral cohort
        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            name="behavioral cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                            "time_value": 30,
                            "time_interval": "day",
                        }
                    ],
                }
            },
        )

        # Create a cohort that references the behavioral cohort
        Cohort.objects.create(
            team=self.team,
            name="cohort with nested behavioral",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "cohort",
                            "value": str(behavioral_cohort.pk),
                        }
                    ],
                }
            },
        )

        # Create a regular cohort
        regular_cohort = Cohort.objects.create(
            team=self.team,
            name="regular cohort not behavioral",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "person", "key": "email", "value": "test@posthog.com"}],
                }
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?hide_behavioral_cohorts=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], regular_cohort.id)

    def test_cohort_activity_log(self):
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"prop": 5})
        Person.objects.create(team=self.team, properties={"prop": 6})

        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "whatever", "groups": [{"properties": {"prop": "5"}}]},
        )

        cohort = Cohort.objects.filter(team=self.team).last()
        assert cohort is not None

        self.assert_cohort_activity(
            cohort_id=cohort.pk,
            expected=[
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "created",
                    "scope": "Cohort",
                    "item_id": str(cohort.pk),
                    "detail": {"changes": [], "trigger": None, "name": "whatever", "short_id": None, "type": None},
                    "created_at": mock.ANY,
                }
            ],
        )

        self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.pk}",
            data={"name": "woohoo", "groups": [{"properties": {"prop": "6"}}]},
        )
        cohort.refresh_from_db()
        assert cohort.name == "woohoo"

        self.assert_cohort_activity(
            cohort_id=cohort.pk,
            expected=[
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "updated",
                    "scope": "Cohort",
                    "item_id": str(cohort.pk),
                    "detail": {
                        "changes": [
                            {
                                "type": "Cohort",
                                "action": "changed",
                                "field": "name",
                                "before": "whatever",
                                "after": "woohoo",
                            },
                            {
                                "type": "Cohort",
                                "action": "changed",
                                "field": "groups",
                                "before": [
                                    {
                                        "days": None,
                                        "count": None,
                                        "label": None,
                                        "end_date": None,
                                        "event_id": None,
                                        "action_id": None,
                                        "properties": [{"key": "prop", "type": "person", "value": "5"}],
                                        "start_date": None,
                                        "count_operator": None,
                                    }
                                ],
                                "after": [{"properties": [{"key": "prop", "type": "person", "value": "6"}]}],
                            },
                        ],
                        "trigger": None,
                        "name": "woohoo",
                        "short_id": None,
                        "type": None,
                    },
                    "created_at": mock.ANY,
                },
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "created",
                    "scope": "Cohort",
                    "item_id": str(cohort.pk),
                    "detail": {"changes": [], "trigger": None, "name": "whatever", "short_id": None, "type": None},
                    "created_at": mock.ANY,
                },
            ],
        )

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

    def test_filter_by_cohort_prop_from_clickhouse(self):
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
    @patch("posthog.tasks.calculate_cohort.chain")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_and_calculating_with_cycle(
        self, patch_calculate_cohort_delay, patch_calculate_cohort_si, patch_chain, patch_capture
    ):
        mock_chain_instance = MagicMock()
        patch_chain.return_value = mock_chain_instance

        # Count total calculation calls (both delay and chain)
        def get_total_calculation_calls():
            return patch_calculate_cohort_delay.call_count + patch_chain.call_count

        # Cohort A
        response_a = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort A", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(get_total_calculation_calls(), 1)

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
        self.assertEqual(get_total_calculation_calls(), 2)

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
        self.assertEqual(get_total_calculation_calls(), 3)

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
        self.assertEqual(get_total_calculation_calls(), 3)

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
        self.assertEqual(get_total_calculation_calls(), 3)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.chain")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_with_non_directed_cycle(
        self, patch_calculate_cohort_delay, patch_calculate_cohort_si, patch_chain, patch_capture
    ):
        mock_chain_instance = MagicMock()
        patch_chain.return_value = mock_chain_instance

        # Count total calculation calls (both delay and chain)
        def get_total_calculation_calls():
            return patch_calculate_cohort_delay.call_count + patch_chain.call_count

        # Cohort A
        response_a = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort A", "groups": [{"properties": {"team_id": 5}}]},
        )
        self.assertEqual(get_total_calculation_calls(), 1)

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
        self.assertEqual(get_total_calculation_calls(), 2)

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
        self.assertEqual(get_total_calculation_calls(), 3)

        # Update Cohort C
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_c.json()['id']}",
            data={
                "name": "Cohort C, reloaded",
            },
        )
        # it's not a loop because C depends on A & B, B depends on A, and A depends on nothing.
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(get_total_calculation_calls(), 4)

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
                                "operator": "exact",
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
    def test_calculating_with_new_cohort_event_filters(self, patch_capture):
        _create_person(
            distinct_ids=["p1"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            properties={"$filter_prop": "something"},
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
            properties={"$filter_prop": "something2"},
            timestamp=datetime.now() - timedelta(hours=12),
        )

        _create_person(
            distinct_ids=["p3"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p3",
            properties={"$filter_prop": "something2"},
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
                                "type": "OR",
                                "values": [
                                    {
                                        "key": "$pageview",
                                        "event_type": "events",
                                        "time_value": 1,
                                        "time_interval": "day",
                                        "value": "performed_event",
                                        "type": "behavioral",
                                        "negation": False,
                                        "event_filters": [
                                            {
                                                "key": "$filter_prop",
                                                "value": "something",
                                                "operator": "exact",
                                                "type": "event",
                                            }
                                        ],
                                    }
                                ],
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
        self.assertEqual(1, len(response.json()["results"]))

    @patch("posthog.api.cohort.report_user_action")
    def test_creating_update_and_calculating_with_new_cohort_query(self, patch_capture):
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

        flush_persons_and_events()

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "is_static": True,
                "query": {
                    "kind": "ActorsQuery",
                    "properties": [
                        {
                            "key": "$some_prop",
                            "value": "something",
                            "type": "person",
                            "operator": PropertyOperator.EXACT,
                        }
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        cohort_id = response.json()["id"]

        while response.json()["is_calculating"]:
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")

        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(1, len(response.json()["results"]))

    @patch("posthog.api.cohort.report_user_action")
    def test_creating_update_and_calculating_with_new_cohort_query_dynamic_error(self, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "query": {
                    "kind": "ActorsQuery",
                    "properties": [
                        {
                            "key": "$some_prop",
                            "value": "something",
                            "type": "person",
                            "operator": PropertyOperator.EXACT,
                        }
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

    @patch("posthog.api.cohort.report_user_action")
    def test_creating_with_query_and_fields(self, patch_capture):
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
        _create_event(team=self.team, event="$pageview", distinct_id="p4", timestamp=datetime.now())
        _create_event(team=self.team, event="$pageview", distinct_id="p4", timestamp=datetime.now())
        flush_persons_and_events()

        def _calc(query: str) -> int:
            response = self.client.post(
                f"/api/projects/{self.team.id}/cohorts",
                data={
                    "name": "cohort A",
                    "is_static": True,
                    "query": {
                        "kind": "HogQLQuery",
                        "query": query,
                    },
                },
            )
            cohort_id = response.json()["id"]
            while response.json()["is_calculating"]:
                response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}")
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/persons/?cohort={cohort_id}")
            return len(response.json()["results"])

        # works with "actor_id"
        self.assertEqual(2, _calc("select id as actor_id from persons where properties.$some_prop='not it'"))

        # works with "person_id"
        self.assertEqual(2, _calc("select id as person_id from persons where properties.$some_prop='not it'"))

        # works with "id"
        self.assertEqual(2, _calc("select id from persons where properties.$some_prop='not it'"))

        # only "p4" had events
        self.assertEqual(1, _calc("select person_id from events"))

        # works with selecting anything from persons and events
        self.assertEqual(4, _calc("select 1 from persons"))
        self.assertEqual(1, _calc("select 1 from events"))

        # raises on all other cases
        query_post_response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort A",
                "is_static": True,
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select 1 from groups",
                },
            },
        )
        query_get_response = self.client.get(
            f"/api/projects/{self.team.id}/cohorts/{query_post_response.json()['id']}/"
        )

        self.assertEqual(query_post_response.status_code, 201)
        self.assertEqual(query_get_response.status_code, 200)
        self.assertEqual(
            query_get_response.json()["errors_calculating"], 1
        )  # Should be because selecting from groups is not allowed

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
                "detail": "Must contain a 'properties' key with type and values",
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
                                "operator": "exact",
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
                                "operator": "exact",
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
                                "operator": "exact",
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

    def test_duplicating_dynamic_cohort_as_static(self):
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
                                "operator": "exact",
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

    def test_duplicating_dynamic_cohort_as_dynamic(self):
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
                                "type": "OR",
                                "values": [
                                    {
                                        "key": "$initial_geoip_subdivision_1_name",
                                        "type": "person",
                                        "value": "New South Wales",
                                        "negation": False,
                                        "operator": "exact",
                                    },
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": "@byda.com.au",
                                        "negation": False,
                                        "operator": "exact",
                                    },
                                ],
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        cohort_id = response.json()["id"]

        payload = {
            "id": cohort_id,
            "name": "cohort A (dynamic copy)",
            "description": "",
            "groups": [],
            "query": None,
            "is_calculating": False,
            "is_static": False,
            "errors_calculating": 0,
            "experiment_set": [],
            "count": 2,
            "deleted": False,
            "filters": {
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$initial_geoip_subdivision_1_name",
                                    "type": "person",
                                    "value": "New South Wales",
                                    "negation": False,
                                    "operator": "exact",
                                },
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@byda.com.au",
                                    "negation": False,
                                    "operator": "exact",
                                },
                            ],
                        }
                    ],
                }
            },
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        cohort_data = response.json()
        self.assertIsNotNone(cohort_data.get("id"))

        new_cohort_id = response.json()["id"]
        new_cohort = Cohort.objects.get(pk=new_cohort_id)
        self.assertEqual(new_cohort.is_static, False)
        self.assertEqual(new_cohort.name, "cohort A (dynamic copy)")

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
    def test_cohort_property_validation_missing_operator(self, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort missing operator",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "some_prop",
                                "value": "some_value",
                                "type": "person",
                                # Missing operator
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Missing required keys for person filter: operator")

    @patch("posthog.api.cohort.report_user_action")
    def test_cohort_property_validation_missing_value(self, patch_capture):
        self.maxDiff = None
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort missing value",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "some_prop",
                                "type": "person",
                                "operator": "exact",
                                # Missing value
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Missing required keys for person filter: value")

    @patch("posthog.api.cohort.report_user_action")
    def test_cohort_property_validation_behavioral_filter(self, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort behavioral",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                # Missing event_type
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Missing required keys for behavioral filter: event_type")

    @patch("posthog.api.cohort.report_user_action")
    def test_cohort_property_validation_nested_groups(self, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort nested groups",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "some_prop", "value": "some_value", "type": "person", "operator": "exact"},
                                    {
                                        "key": "another_prop",
                                        "type": "person",
                                        # Missing value and operator
                                    },
                                ],
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Missing required keys for person filter: value, operator")

    @patch("posthog.api.cohort.report_user_action")
    def test_cohort_property_validation_is_set_operator(self, patch_capture):
        # Test that is_set operator doesn't require a value
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort is_set",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [{"key": "some_prop", "type": "person", "operator": "is_set"}],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.json()["id"], None)

    @patch("posthog.api.cohort.report_user_action")
    def test_cohort_property_validation_cohort_filter(self, patch_capture):
        # First create a cohort to reference
        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "first cohort",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [{"key": "some_prop", "value": "some_value", "type": "person", "operator": "exact"}],
                    }
                },
            },
        ).json()

        # Test cohort filter validation
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "cohort with cohort filter",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "id",
                                "type": "cohort",
                                # Missing value (cohort id)
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Missing required keys for cohort filter: value")

    @patch("posthog.api.cohort.report_user_action")
    def test_behavioral_filter_with_operator_and_operator_value(self, patch_capture):
        # Valid usage: operator and operator_value present
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "behavioral with operator",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "gte",
                                "operator_value": 5,
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
        # Should create successfully
        self.assertEqual(response.status_code, 200, response.content)

    @patch("posthog.api.cohort.report_user_action")
    def test_behavioral_filter_missing_operator(self, patch_capture):
        # operator_value present but operator missing
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "behavioral missing operator",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator_value": 5,
                            }
                        ],
                    }
                },
            },
        )
        # Should still succeed, as operator is optional
        self.assertEqual(response.status_code, 201, response.content)

    @patch("posthog.api.cohort.report_user_action")
    def test_behavioral_filter_invalid_operator_value_type(self, patch_capture):
        # operator_value as a list (invalid)
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "behavioral invalid operator_value",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "gte",
                                "operator_value": [5],
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("operator_value", str(response.content))

    @patch("posthog.api.cohort.report_user_action")
    def test_behavioral_filter_extra_field_forbidden(self, patch_capture):
        # Extra field not in model
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "behavioral extra field",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "operator": "gte",
                                "operator_value": 5,
                                "not_a_field": 123,
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not_a_field", str(response.content))

    @patch("posthog.api.cohort.report_user_action")
    def test_behavioral_filter_seq_event_types(self, patch_capture):
        # Test with string seq_event
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "behavioral with string seq_event",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "seq_event": "reauthentication_completed",
                                "seq_event_type": "events",
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        # Test with integer seq_event (action ID)
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "behavioral with integer seq_event",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "seq_event": 1,  # action ID
                                "seq_event_type": "actions",
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

        # Test with null seq_event
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "behavioral with null seq_event",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "seq_event": None,
                                "seq_event_type": None,
                            }
                        ],
                    }
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_create_cohort_in_specific_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "Test Cohort in folder",
                "groups": [{"properties": {"prop": "5"}}],
                "_create_in_folder": "Special Folder/Cohorts",
            },
            format="json",
        )
        assert response.status_code == 201, response.json()

        cohort_id = response.json()["id"]
        assert cohort_id is not None

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(team=self.team, ref=str(cohort_id), type="cohort").first()
        assert fs_entry is not None, "A FileSystem entry was not created for this Cohort."
        assert (
            "Special Folder/Cohorts" in fs_entry.path
        ), f"Expected path to include 'Special Folder/Cohorts', got '{fs_entry.path}'."

    @patch("posthog.api.cohort.report_user_action")
    def test_behavioral_filter_with_hogql_event_filter_and_null_value(self, patch_capture):
        payload = {
            "name": "Cohort with HogQL Event Filter and Null Value",
            "filters": {
                "properties": {  # CohortFilters.properties -> Group
                    "type": "OR",
                    "values": [  # Group.values -> list[Union[PropertyFilter, Group]]
                        {
                            "type": "OR",  # Inner Group
                            "values": [
                                {  # PropertyFilter -> BehavioralFilter
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "negation": False,
                                    "key": "PaymentSuccess",
                                    "event_type": "events",
                                    "event_filters": [  # BehavioralFilter.event_filters
                                        {
                                            "key": "to_date(timestamp) = current_date() - INTERVAL '3 days'",
                                            "type": "hogql",  # HogQLFilter
                                            "value": None,  # Testing this null value
                                        },
                                        {
                                            "key": "planId",
                                            "type": "event",  # EventPropFilter
                                            "value": ["UPSC26STARTERV1"],
                                            "operator": "exact",
                                        },
                                    ],
                                    "explicit_datetime": "-30d",
                                }
                            ],
                        }
                    ],
                }
            },
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        cohort_data = response.json()
        self.assertIsNotNone(cohort_data.get("id"))

    def test_cohort_serializer_includes_cohort_type_fields(self):
        """Test that cohort serializer includes cohort_type and computed fields"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "test_cohort",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "test_event",
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "events",
                                    }
                                ],
                            }
                        ],
                    }
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertIn("cohort_type", data)
        self.assertIn("has_behavioral_filters", data)
        self.assertIn("is_analytical", data)
        self.assertEqual(data["cohort_type"], "behavioral")
        self.assertTrue(data["has_behavioral_filters"])
        self.assertFalse(data["is_analytical"])

    def test_cohort_type_auto_updated_on_create(self):
        """Test that cohort type is automatically set on creation"""
        # Create cohort with complex behavioral filter
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "complex_behavioral_cohort",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "test_event",
                                        "type": "behavioral",
                                        "value": "performed_event_first_time",
                                        "event_type": "events",
                                    }
                                ],
                            }
                        ],
                    }
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertEqual(data["cohort_type"], "analytical")
        # Complex behavioral filters result in both flags being true:
        # - has_behavioral_filters=True because it has behavioral filters
        # - is_analytical=True because it's an analytical cohort (requires ClickHouse)
        self.assertTrue(data["has_behavioral_filters"])  # Has behavioral filters
        self.assertTrue(data["is_analytical"])  # Is analytical cohort

    def test_cohort_type_auto_updated_on_update(self):
        """Test that cohort type is automatically updated when filters change"""
        # Create a simple behavioral cohort
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "update_test_cohort",
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "test_event",
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "events",
                                    }
                                ],
                            }
                        ],
                    }
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        cohort_id = response.json()["id"]
        self.assertEqual(response.json()["cohort_type"], "behavioral")

        # Update to complex behavioral filter
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "test_event",
                                        "type": "behavioral",
                                        "value": "performed_event_first_time",
                                        "event_type": "events",
                                    }
                                ],
                            }
                        ],
                    }
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cohort_type"], "analytical")

    def test_static_cohort_type_is_behavioral(self):
        """Test that static cohorts are automatically set to behavioral type"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts", data={"name": "static_cohort", "is_static": True}, format="json"
        )
        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertEqual(data["cohort_type"], "behavioral")
        self.assertFalse(data["has_behavioral_filters"])  # No behavioral filters
        self.assertFalse(data["is_analytical"])  # Not analytical

    def test_cohort_type_read_only_in_api(self):
        """Test that cohort_type cannot be directly set via API"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={
                "name": "test_cohort",
                "cohort_type": "analytical",  # Try to force analytical
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "test_event",
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "event_type": "events",
                                    }
                                ],
                            }
                        ],
                    }
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

        # Should be behavioral despite trying to set analytical
        data = response.json()
        self.assertEqual(data["cohort_type"], "behavioral")


class TestCalculateCohortCommand(APIBaseTest):
    def test_calculate_cohort_command_success(self):
        # Create a test cohort
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort 1",
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
        )
        # Call the command
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        with patch("posthog.management.commands.calculate_cohort.calculate_cohort_ch") as mock_calculate_cohort:
            call_command("calculate_cohort", cohort_id=cohort.id, stdout=out)
            # Verify the cohort is calculated
            cohort.refresh_from_db()
            mock_calculate_cohort.assert_called_once_with(cohort.id, cohort.pending_version, None)
            self.assertFalse(cohort.is_calculating)
            self.assertIn(f"Successfully calculated cohort {cohort.id}", out.getvalue())

    def test_calculate_cohort_command_error(self):
        # Create a test cohort
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort 2",
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
        )
        # Call the command
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        with patch(
            "posthog.management.commands.calculate_cohort.calculate_cohort_ch", side_effect=Exception("Test error 2")
        ) as mock_calculate_cohort:
            call_command("calculate_cohort", cohort_id=cohort.id, stdout=out)
            # Verify the error was handled
            cohort.refresh_from_db()
            mock_calculate_cohort.assert_called_once_with(cohort.id, cohort.pending_version, None)
            self.assertFalse(cohort.is_calculating)
            output = out.getvalue()
            self.assertIn("Error calculating cohort: Test error 2", output)
            self.assertIn("Full traceback:", output)
            self.assertIn("Exception: Test error 2", output)


def create_cohort(client: Client, team_id: int, name: str, groups: list[dict[str, Any]]):
    return client.post(f"/api/projects/{team_id}/cohorts", {"name": name, "groups": json.dumps(groups)})


def create_cohort_ok(client: Client, team_id: int, name: str, groups: list[dict[str, Any]]):
    response = create_cohort(client=client, team_id=team_id, name=name, groups=groups)
    assert response.status_code == 201, response.content
    return response.json()
