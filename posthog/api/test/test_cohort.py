import json
from datetime import datetime, timedelta
from typing import Any, Optional

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_person,
    flush_persons_and_events,
)
from unittest import mock
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import Client
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.schema import PersonsOnEventsMode, PropertyOperator

from posthog.api.test.test_exports import TestExportMixin
from posthog.clickhouse.client.execute import sync_execute
from posthog.models import Action, FeatureFlag, Person, User
from posthog.models.async_deletion.async_deletion import AsyncDeletion
from posthog.models.cohort import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.models.property import BehavioralPropertyType
from posthog.models.team.team import Team
from posthog.tasks.calculate_cohort import (
    calculate_cohort_ch,
    calculate_cohort_from_list,
    get_cohort_calculation_candidates_queryset,
    increment_version_and_enqueue_calculate_cohort,
)

from ee.clickhouse.materialized_columns.analyze import materialize


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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay", side_effect=calculate_cohort_ch)
    @patch("posthog.models.cohort.util.sync_execute", side_effect=sync_execute)
    def test_creating_update_and_calculating(
        self, patch_sync_execute, patch_calculate_cohort, patch_capture, patch_on_commit
    ):
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
            self.assertLessEqual(
                {"name": "whatever2", "description": "A great cohort!"}.items(), response.json().items()
            )
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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay", side_effect=calculate_cohort_ch)
    @patch("posthog.models.cohort.util.sync_execute", side_effect=sync_execute)
    def test_action_persons_on_events(self, patch_sync_execute, patch_calculate_cohort, patch_capture, patch_on_commit):
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

        with self.assertNumQueries(13):
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

        with self.assertNumQueries(13):
            response = self.client.get(f"/api/projects/{self.team.id}/cohorts")
            assert len(response.json()["results"]) == 3

    def test_static_cohort_csv_upload_end_to_end(self):
        """Test CSV upload end-to-end with actual celery task execution"""
        self.team.app_urls = ["http://somewebsite.com"]
        self.team.save()
        Person.objects.create(team=self.team, properties={"email": "email@example.org"})
        Person.objects.create(team=self.team, distinct_ids=["123"])
        Person.objects.create(team=self.team, distinct_ids=["456"])
        Person.objects.create(team=self.team, distinct_ids=["0"])  # Test edge case: '0' as distinct_id

        csv = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID
email@example.org
123
0
"""
            ),
            content_type="application/csv",
        )

        with self.settings(CELERY_TASK_ALWAYS_EAGER=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/cohorts/",
                {"name": "test", "csv": csv, "is_static": True},
                format="multipart",
            )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])
        self.assertFalse(cohort.is_calculating)
        # Verify CSV parsing worked correctly - should include 123 and 0 (only existing distinct_ids)
        cohort_people = Person.objects.filter(cohort__id=cohort.id)
        distinct_ids = set()
        for person in cohort_people:
            distinct_ids.update(person.distinct_ids)
        self.assertEqual(distinct_ids, {"123", "0"})

        # Test CSV update
        csv_update = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID
456
"""
            ),
            content_type="application/csv",
        )

        with self.settings(CELERY_TASK_ALWAYS_EAGER=True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/cohorts/{cohort.id}",
                {"name": "test", "csv": csv_update},
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        # Verify CSV update worked - 456 should now be included
        cohort_people = Person.objects.filter(cohort__id=cohort.id)
        distinct_ids = set()
        for person in cohort_people:
            distinct_ids.update(person.distinct_ids)
        self.assertIn("456", distinct_ids)  # New ID should be included

        # Test name-only update without CSV
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}",
            {"name": "test2"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.name, "test2")
        # Verify distinct_ids remain the same after name-only update
        cohort_people = Person.objects.filter(cohort__id=cohort.id)
        distinct_ids = set()
        for person in cohort_people:
            distinct_ids.update(person.distinct_ids)
        self.assertIn("456", distinct_ids)  # Should still contain 456

    def test_static_cohort_create_and_patch_with_query(self):
        _create_person(
            distinct_ids=["123"],
            team_id=self.team.pk,
            properties={"$some_prop": "not it"},
        )
        _create_person(
            distinct_ids=["p2"],
            team_id=self.team.pk,
            properties={"$some_prop": "something"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp=datetime.now() - timedelta(hours=12),
        )

        flush_persons_and_events()

        csv = SimpleUploadedFile(
            "example.csv",
            str.encode(
                """
User ID
email@example.org
123
0
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
        cohort = Cohort.objects.get(pk=response.json()["id"])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.pk}",
            data={
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
                }
            },
        )
        self.assertEqual(response.status_code, 200)
        cohort.refresh_from_db()

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

    @parameterized.expand([("distinct-id",), ("distinct_id",)])
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay", side_effect=calculate_cohort_from_list)
    def test_static_cohort_csv_upload_with_distinct_id_column(
        self, distinct_id_column_header, patch_calculate_cohort_from_list
    ):
        """Test multi-column CSV upload with distinct_id column"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["user456"])
        person3 = Person.objects.create(team=self.team, distinct_ids=["0"])  # Test edge case: '0' as distinct_id

        csv = SimpleUploadedFile(
            "multicolumn.csv",
            str.encode(
                f"""name,{distinct_id_column_header},email
John Doe,user123,john@example.com
Jane Smith,user456,jane@example.com
Zero User,0,zero@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_multicolumn", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify all three persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 3)

        # Verify specific persons are in the cohort
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)
        self.assertIn(str(person3.uuid), person_uuids_in_cohort)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_multicolumn_without_valid_identifier_fails(
        self, patch_calculate_cohort_from_list
    ):
        """Test that multi-column CSV without distinct_id column fails with clear error"""
        csv = SimpleUploadedFile(
            "no_distinct_id.csv",
            str.encode(
                """name,age
John Doe,30
Jane Smith,25
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_fail", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["attr"], "csv")
        self.assertIn("distinct_id", response_data["detail"])
        self.assertIn("name, age", response_data["detail"])
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 0)

    @parameterized.expand([("person-id",), ("person_id",), ("Person .id",)])
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay", side_effect=calculate_cohort_from_list)
    def test_static_cohort_csv_upload_with_person_uuid_column(
        self, person_id_column_header, patch_calculate_cohort_from_list
    ):
        """Test CSV upload with person_id column using async task"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["user456"])

        csv = SimpleUploadedFile(
            f"{person_id_column_header}.csv",
            str.encode(
                f"""name,{person_id_column_header},email
John Doe,{person1.uuid},john@example.com
Jane Smith,{person2.uuid},jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": f"test_{person_id_column_header}", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

        # Verify specific persons are in the cohort
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay", side_effect=calculate_cohort_from_list)
    def test_static_cohort_csv_upload_person_id_preference_over_email(self, patch_calculate_cohort_from_list):
        """Test that person_id is preferred over email when both columns are present"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["user456"])

        # Create persons with emails that would match if email was used instead
        person_with_email1 = Person.objects.create(
            team=self.team, distinct_ids=["email_user1"], properties={"email": "john@example.com"}
        )
        person_with_email2 = Person.objects.create(
            team=self.team, distinct_ids=["email_user2"], properties={"email": "jane@example.com"}
        )

        csv = SimpleUploadedFile(
            "person_id_and_email.csv",
            str.encode(
                f"""name,person_id,email
John Doe,{person1.uuid},john@example.com
Jane Smith,{person2.uuid},jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_person_id_over_email", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

        # Verify specific persons are in the cohort (the ones matched by person_id, not email)
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)

        # Verify that persons matched by email are NOT in the cohort
        self.assertNotIn(str(person_with_email1.uuid), person_uuids_in_cohort)
        self.assertNotIn(str(person_with_email2.uuid), person_uuids_in_cohort)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay", side_effect=calculate_cohort_from_list)
    def test_static_cohort_csv_upload_distinct_id_preference_over_email(self, patch_calculate_cohort_from_list):
        """Test that distinct_id is preferred over email when both columns are present"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["user456"])

        # Create persons with emails that would match if email was used instead
        person_with_email1 = Person.objects.create(
            team=self.team, distinct_ids=["email_user1"], properties={"email": "john@example.com"}
        )
        person_with_email2 = Person.objects.create(
            team=self.team, distinct_ids=["email_user2"], properties={"email": "jane@example.com"}
        )

        csv = SimpleUploadedFile(
            "distinct_id_and_email.csv",
            str.encode(
                """name,distinct_id,email
John Doe,user123,john@example.com
Jane Smith,user456,jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_distinct_id_over_email", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

        # Verify specific persons are in the cohort (the ones matched by distinct_id, not email)
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)

        # Verify that persons matched by email are NOT in the cohort
        self.assertNotIn(str(person_with_email1.uuid), person_uuids_in_cohort)
        self.assertNotIn(str(person_with_email2.uuid), person_uuids_in_cohort)

    def test_static_cohort_with_manually_added_person_ids(self):
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["user456"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {
                "name": f"test_upload_with_person_ids",
                "_create_static_person_ids": [person1.uuid, person2.uuid],
                "is_static": True,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

        # Verify specific persons are in the cohort
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)

    def test_static_cohort_csv_and_manually_added(self):
        """Test CSV upload with person_id column using async task"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["user456"])

        csv = SimpleUploadedFile(
            f"{person1}.csv",
            str.encode(
                f"""name,person_id,email
John Doe,{person1.uuid},john@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {
                "name": f"test_csv_and_manual",
                "csv": csv,
                "_create_static_person_ids": [person2.uuid],
                "is_static": True,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

        # Verify specific persons are in the cohort
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_person_id_preference_over_distinct_id(self, patch_calculate_cohort_from_list):
        """Test that person_id is preferred over distinct_id when both columns are present"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["distinct123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["distinct456"])

        csv = SimpleUploadedFile(
            "both_columns.csv",
            str.encode(
                f"""name,person_id,distinct_id,email
John Doe,{person1.uuid},ignore_this_distinct_id,john@example.com
Jane Smith,{person2.uuid},ignore_this_too,jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_preference", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        # Should use person_id task, not distinct_id task
        patch_calculate_cohort_from_list.assert_called_once_with(
            response.json()["id"], [str(person1.uuid), str(person2.uuid)], team_id=self.team.id, id_type="person_id"
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_with_empty_person_ids(self, patch_calculate_cohort_from_list):
        """Test CSV with person_id column but some empty values"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])

        csv = SimpleUploadedFile(
            "empty_person_ids.csv",
            str.encode(
                f"""name,person_id,email
John Doe,{person1.uuid},john@example.com
Empty Person,,empty@example.com
Jane Smith,   ,jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_empty_person_ids", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        # Should only include the non-empty person_id
        patch_calculate_cohort_from_list.assert_called_once_with(
            response.json()["id"], [str(person1.uuid)], team_id=self.team.id, id_type="person_id"
        )

    def test_static_cohort_csv_upload_multicolumn_without_any_id_fails(self):
        """Test that multi-column CSV without person_id or distinct_id column fails with updated error message"""
        csv = SimpleUploadedFile(
            "no_id_columns.csv",
            str.encode(
                """name,age
John Doe,30
Jane Smith,25
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_fail", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["attr"], "csv")
        # Should reference all supported ID column types with clearer messaging
        self.assertIn("at least one column with a supported ID header", response_data["detail"])
        self.assertIn("person_id", response_data["detail"])
        self.assertIn("distinct_id", response_data["detail"])
        self.assertIn("name, age", response_data["detail"])

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_empty_file_fails(self, patch_calculate_cohort_from_list):
        """Test that empty CSV file fails with clear error"""
        csv = SimpleUploadedFile(
            "empty.csv",
            str.encode(""),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_empty", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["attr"], "csv")
        self.assertIn("empty", response_data["detail"])
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 0)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_no_valid_ids_fails(self, patch_calculate_cohort_from_list):
        """Test that CSV with no valid distinct IDs fails with clear error"""
        csv = SimpleUploadedFile(
            "no_ids.csv",
            str.encode(
                """,,,
,
,
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_no_ids", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["attr"], "csv")
        self.assertIn("no valid person IDs, distinct IDs, or email addresses", response_data["detail"])
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 0)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_single_column_backwards_compatibility(self, patch_calculate_cohort_from_list):
        """Test that single-column CSV still works (backwards compatibility)"""
        Person.objects.create(team=self.team, distinct_ids=["legacy_user"])

        csv = SimpleUploadedFile(
            "single_column.csv",
            str.encode(
                """legacy_user
another_user
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_legacy", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        patch_calculate_cohort_from_list.assert_called_with(
            response.json()["id"], ["legacy_user", "another_user"], team_id=self.team.id, id_type="distinct_id"
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_single_column_person_ids(self, patch_calculate_cohort_from_list):
        """Test that single-column CSV with person_id header is treated as person UUIDs"""
        person1 = Person.objects.create(team=self.team)
        person2 = Person.objects.create(team=self.team)

        csv = SimpleUploadedFile(
            "person_ids.csv",
            str.encode(
                f"""person_id
{person1.uuid}
{person2.uuid}
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_person_ids", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        # Single column format with person_id header uses person UUID processing
        patch_calculate_cohort_from_list.assert_called_with(
            response.json()["id"], [str(person1.uuid), str(person2.uuid)], team_id=self.team.id, id_type="person_id"
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_whitespace_handling(self, patch_calculate_cohort_from_list):
        """Test that whitespace is properly trimmed from distinct IDs in multi-column CSV"""
        Person.objects.create(team=self.team, distinct_ids=["user123"])
        Person.objects.create(team=self.team, distinct_ids=["user456"])

        csv = SimpleUploadedFile(
            "whitespace.csv",
            str.encode(
                """name,distinct_id,email
John Doe,  user123  ,john@example.com
Jane Smith,	user456	,jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_whitespace", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        # Verify whitespace is trimmed from distinct IDs
        patch_calculate_cohort_from_list.assert_called_with(
            response.json()["id"], ["user123", "user456"], team_id=self.team.id, id_type="distinct_id"
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_with_commas_in_distinct_ids(self, patch_calculate_cohort_from_list):
        """Test that CSV quoting/escaping works when distinct IDs contain commas"""
        Person.objects.create(team=self.team, distinct_ids=["user,123"])
        Person.objects.create(team=self.team, distinct_ids=["user,456,special"])

        csv = SimpleUploadedFile(
            "comma_ids.csv",
            str.encode(
                """name,distinct_id,email
"John Doe","user,123","john@example.com"
"Jane Smith","user,456,special","jane@example.com"
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_comma_ids", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        # Verify comma-containing distinct IDs are correctly parsed
        patch_calculate_cohort_from_list.assert_called_with(
            response.json()["id"], ["user,123", "user,456,special"], team_id=self.team.id, id_type="distinct_id"
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_with_quotes_in_distinct_ids(self, patch_calculate_cohort_from_list):
        """Test that CSV escaping works when distinct IDs contain quotes"""
        Person.objects.create(team=self.team, distinct_ids=['user"123'])
        Person.objects.create(team=self.team, distinct_ids=['user"special"456'])

        csv = SimpleUploadedFile(
            "quote_ids.csv",
            str.encode(
                """name,distinct_id,email
"John Doe","user""123","john@example.com"
"Jane Smith","user""special""456","jane@example.com"
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_quote_ids", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        # Verify quote-containing distinct IDs are correctly parsed
        patch_calculate_cohort_from_list.assert_called_with(
            response.json()["id"], ['user"123', 'user"special"456'], team_id=self.team.id, id_type="distinct_id"
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_upload_with_inconsistent_column_count(self, patch_calculate_cohort_from_list):
        """Test that rows with incorrect column count are gracefully skipped in multi-column CSV"""
        Person.objects.create(team=self.team, distinct_ids=["user123"])
        Person.objects.create(team=self.team, distinct_ids=["user456"])

        csv = SimpleUploadedFile(
            "inconsistent_columns.csv",
            str.encode(
                """email,distinct_id
myemail@posthog.com,user123
incomplete_row_missing_distinct_id
anotheremail@posthog.com,user456
another_incomplete_row
user789
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_inconsistent", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(patch_calculate_cohort_from_list.call_count, 1)
        # Verify only rows with correct column count are processed
        # Should skip: "incomplete_row_missing_distinct_id", "another_incomplete_row", "user789"
        # Should include: "user123", "user456"
        patch_calculate_cohort_from_list.assert_called_with(
            response.json()["id"], ["user123", "user456"], team_id=self.team.id, id_type="distinct_id"
        )

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    def test_static_cohort_csv_sets_is_calculating(self, patch_calculate_cohort_from_list):
        """Test that is_calculating is set to True immediately when CSV is uploaded"""
        Person.objects.create(team=self.team, distinct_ids=["user123"])

        csv = SimpleUploadedFile(
            "test.csv",
            str.encode(
                """distinct_id
user123
user456
"""
            ),
            content_type="application/csv",
        )

        # Create cohort with CSV upload
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_calculating", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort_id = response.json()["id"]

        # Check that is_calculating was set to True
        cohort = Cohort.objects.get(pk=cohort_id)
        self.assertTrue(cohort.is_calculating, "is_calculating should be True immediately after CSV upload")

        # Verify the task was called
        patch_calculate_cohort_from_list.assert_called_once()

    def test_static_cohort_csv_resets_is_calculating_on_error(self):
        """Test that is_calculating is reset to False when CSV processing fails"""
        # Try to upload an invalid CSV that will cause an error
        csv = SimpleUploadedFile(
            "invalid.csv",
            str.encode(""),  # Empty CSV will trigger an error
            content_type="application/csv",
        )

        # Try to create cohort with invalid CSV
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_error", "csv": csv, "is_static": True},
            format="multipart",
        )

        # Should get an error response
        self.assertEqual(response.status_code, 400)

        # Check that no cohort was created with is_calculating stuck at True
        # (The cohort shouldn't be created at all, but if error handling was wrong
        # it might leave a cohort in calculating state)
        calculating_cohorts = Cohort.objects.filter(team=self.team, name="test_error", is_calculating=True)
        self.assertEqual(calculating_cohorts.count(), 0, "No cohort should be left in calculating state after error")

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_static_cohort_to_dynamic_cohort(
        self, patch_calculate_cohort, patch_calculate_cohort_from_list, patch_on_commit
    ):
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
        # After CSV upload, is_calculating should be True since processing starts immediately
        self.assertTrue(response.json()["is_calculating"])
        self.assertTrue(Cohort.objects.get(pk=response.json()["id"]).is_calculating)

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

    def test_cohort_list_with_type_filter(self):
        Person.objects.create(team=self.team, properties={"prop": 5})

        # Create dynamic cohort
        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "dynamic_cohort", "groups": [{"properties": {"prop": 5}}]},
        )

        # Create static cohort
        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "static_cohort", "is_static": True},
        )

        # Test no filter returns both
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts").json()
        self.assertEqual(len(response["results"]), 2)

        # Test static filter
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?type=static").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["name"], "static_cohort")
        self.assertTrue(response["results"][0]["is_static"])

        # Test dynamic filter
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?type=dynamic").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["name"], "dynamic_cohort")
        self.assertFalse(response["results"][0]["is_static"])

    def test_cohort_list_with_created_by_filter(self):
        Person.objects.create(team=self.team, properties={"prop": 5})

        # Create cohorts by self.user
        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "self_user_cohort_1", "groups": [{"properties": {"prop": 5}}]},
        )

        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "self_user_cohort_2", "groups": [{"properties": {"prop": 5}}]},
        )
        other_user = User.objects.create_user(email="other@test.com", password="password", first_name="Other")
        other_user_cohort = Cohort.objects.create(
            team=self.team,
            name="other_user_cohort",
            created_by=other_user,
        )

        # Test no filter returns all cohorts
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts").json()
        self.assertEqual(len(response["results"]), 3)

        # Test filter by self.user's cohorts
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?created_by_id={self.user.id}").json()
        self.assertEqual(len(response["results"]), 2)
        for cohort in response["results"]:
            self.assertEqual(cohort["created_by"]["id"], self.user.id)
            self.assertEqual(cohort["name"][:-2], "self_user_cohort")

        # Test filter by other_user's cohorts
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?created_by_id={other_user.id}").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["name"], other_user_cohort.name)

        # Test filter by blank user (should return no cohorts)
        blank_user = User.objects.create_user(email="blank@test.com", password="password", first_name="blank")
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?created_by_id={blank_user.id}").json()
        self.assertEqual(len(response["results"]), 0)

    def test_cohort_list_with_combined_filters(self):
        Person.objects.create(team=self.team, properties={"prop": 5})

        # Create dynamic cohort
        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "dynamic_test", "groups": [{"properties": {"prop": 5}}]},
        )

        # Create static cohort
        self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "static_test", "is_static": True},
        )

        # Test combined type and search filters
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?type=dynamic&search=dynamic").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["name"], "dynamic_test")
        self.assertFalse(response["results"][0]["is_static"])

        # Test combined filters with no matches
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts?type=static&search=dynamic").json()
        self.assertEqual(len(response["results"]), 0)

        # Test all filters combined
        response = self.client.get(
            f"/api/projects/{self.team.id}/cohorts?type=static&search=static&created_by_id={self.user.id}"
        ).json()
        self.assertEqual(len(response["results"]), 1)
        self.assertEqual(response["results"][0]["name"], "static_test")
        self.assertTrue(response["results"][0]["is_static"])
        self.assertEqual(response["results"][0]["created_by"]["id"], self.user.id)

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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_cohort_activity_log(self, patch_on_commit):
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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.chain")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_and_calculating_with_cycle(
        self, patch_calculate_cohort_delay, patch_calculate_cohort_si, patch_chain, patch_capture, patch_on_commit
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
        self.assertLessEqual(
            {
                "detail": "Cohorts cannot reference other cohorts in a loop.",
                "type": "validation_error",
            }.items(),
            response.json().items(),
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
        self.assertLessEqual(
            {
                "detail": "Cohorts cannot reference other cohorts in a loop.",
                "type": "validation_error",
            }.items(),
            response.json().items(),
        )
        self.assertEqual(get_total_calculation_calls(), 3)

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.chain")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_with_non_directed_cycle(
        self, patch_calculate_cohort_delay, patch_calculate_cohort_si, patch_chain, patch_capture, patch_on_commit
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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_creating_update_and_calculating_with_invalid_cohort(
        self, patch_calculate_cohort, patch_capture, patch_on_commit
    ):
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
        self.assertLessEqual(
            {"detail": "Invalid Cohort ID in filter", "type": "validation_error"}.items(),
            response.json().items(),
        )
        self.assertEqual(patch_calculate_cohort.call_count, 1)

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    def test_creating_update_and_calculating_with_new_cohort_filters(self, patch_capture, patch_on_commit):
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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    def test_calculating_with_new_cohort_event_filters(self, patch_capture, patch_on_commit):
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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    def test_cohort_with_is_set_filter_missing_value(self, patch_capture, patch_on_commit):
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
        self.assertLessEqual(
            {
                "detail": "Must contain a 'properties' key with type and values",
                "type": "validation_error",
            }.items(),
            update_response.json().items(),
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
        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Behavioral filters cannot be added to cohorts used in feature flags.",
                "attr": "filters",
            }.items(),
            response.json().items(),
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
        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "A cohort dependency (cohort XX) has filters based on events. These cohorts can't be used in feature flags.",
                "attr": "filters",
            }.items(),
            response.json().items(),
        )

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_duplicating_dynamic_cohort_as_static(self, patch_on_commit):
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

    def test_duplicating_static_cohort_as_static(self):
        p1 = _create_person(distinct_ids=["p1"], team_id=self.team.pk)
        p2 = _create_person(distinct_ids=["p2"], team_id=self.team.pk)

        flush_persons_and_events()

        # Create static cohort
        cohort = Cohort.objects.create(
            team=self.team,
            name="static cohort A",
            is_static=True,
        )
        cohort.insert_users_list_by_uuid([str(p1.uuid), str(p2.uuid)], team_id=self.team.pk)

        # Verify original cohort has people
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 2, "Original cohort should have 2 people")

        # Duplicate static cohort as static
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort.pk}/duplicate_as_static_cohort")
        self.assertEqual(response.status_code, 200, response.content)

        new_cohort_id = response.json()["id"]
        new_cohort = Cohort.objects.get(pk=new_cohort_id)

        # Verify the duplicated cohort
        self.assertEqual(new_cohort.name, "static cohort A (static copy)")
        self.assertEqual(new_cohort.is_static, True)
        new_cohort.refresh_from_db()
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

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    def test_behavioral_filter_with_operator_and_operator_value(self, patch_capture, patch_on_commit):
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
                                "time_value": 30,
                                "time_interval": "day",
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
                                "time_value": 30,
                                "time_interval": "day",
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
                                "time_value": 30,
                                "time_interval": "day",
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
                                "time_value": 30,
                                "time_interval": "day",
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
                                "time_value": 30,
                                "time_interval": "day",
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

    def test_remove_person_from_static_cohort(self):
        static_cohort = Cohort.objects.create(
            team=self.team,
            name="Test Static Cohort",
            is_static=True,
        )

        personToRemove = _create_person(
            team_id=self.team.pk, distinct_ids=["test-person-to-remove"], properties={"email": "test@example.com"}
        )
        personToKeep = _create_person(
            team_id=self.team.pk, distinct_ids=["test-person-to-keep"], properties={"email": "test@example.com"}
        )
        flush_persons_and_events()
        static_cohort.insert_users_by_list(["test-person-to-remove", "test-person-to-keep"])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{static_cohort.id}/remove_person_from_static_cohort",
            {"person_id": str(personToRemove.uuid)},
            format="json",
        )

        assert response.json() == {"success": True}
        assert response.status_code == 200

        # Verify activity was logged
        activity_response = self._get_cohort_activity(static_cohort.id)
        activity = activity_response["results"]
        assert len(activity) == 1
        activity_entry = activity[0]
        assert activity_entry["activity"] == "person_removed_manually"
        assert activity_entry["scope"] == "Cohort"
        assert activity_entry["item_id"] == str(static_cohort.id)
        assert activity_entry["user"]["email"] == self.user.email

        # Verify only the correct person was removed
        cohort_persons_response = self.client.get(f"/api/cohort/{static_cohort.id}/persons")
        assert cohort_persons_response.status_code == 200
        cohort_persons = cohort_persons_response.json()["results"]
        person_uuids_in_cohort = [p["uuid"] for p in cohort_persons]
        assert str(personToRemove.uuid) not in person_uuids_in_cohort
        assert str(personToKeep.uuid) in person_uuids_in_cohort

    def test_remove_person_from_static_cohort_validation_errors(self):
        static_cohort = Cohort.objects.create(
            team=self.team,
            name="Test Static Cohort",
            is_static=True,
        )

        dynamic_cohort = Cohort.objects.create(
            team=self.team,
            name="Test Dynamic Cohort",
            is_static=False,
        )

        # Test missing person_id
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{static_cohort.id}/remove_person_from_static_cohort",
            {},
            format="json",
        )
        assert response.status_code == 400
        assert "person_id is required" in response.json()["detail"]

        # Test non-string person_id
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{static_cohort.id}/remove_person_from_static_cohort",
            {"person_id": 123},
            format="json",
        )
        assert response.status_code == 400
        assert "person_id must be a string" in response.json()["detail"]

        # Test person_id that is not a valid UUID
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{static_cohort.id}/remove_person_from_static_cohort",
            {"person_id": "a"},
            format="json",
        )
        assert response.status_code == 400
        assert "person_id must be a valid UUID" in response.json()["detail"]

        # Test non-static cohort
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{dynamic_cohort.id}/remove_person_from_static_cohort",
            {"person_id": "some-uuid"},
            format="json",
        )
        assert response.status_code == 400
        assert "Can only remove users from static cohorts" in response.json()["detail"]

    def test_remove_person_from_static_cohort_person_not_in_cohort(self):
        static_cohort = Cohort.objects.create(
            team=self.team,
            name="Test Static Cohort",
            is_static=True,
        )
        # Person does not exist at all
        not_existant_person_UUID = "12345678-1234-1234-1234-123456789abc"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{static_cohort.id}/remove_person_from_static_cohort",
            {"person_id": not_existant_person_UUID},
            format="json",
        )
        assert response.status_code == 404
        assert "Person with this UUID does not exist" in response.json()["detail"]

        # Person exists but is not in the cohort
        person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["test-person-not-in-cohort"],
            properties={"email": "notincohort@example.com"},
        )
        flush_persons_and_events()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{static_cohort.id}/remove_person_from_static_cohort",
            {"person_id": str(person.uuid)},
            format="json",
        )

        assert response.status_code == 404
        assert "Person is not part of the cohort" in response.json()["detail"]

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.models.cohort.dependencies._on_cohort_changed")
    @patch("posthog.tasks.calculate_cohort.increment_version_and_enqueue_calculate_cohort")
    def test_cohort_update_recalculated_after_caching(
        self,
        patch_calculate: MagicMock,
        patch_cohort_changed: MagicMock,
        patch_on_commit: MagicMock,
    ) -> None:
        calls = []
        patch_calculate.side_effect = lambda *a, **kw: calls.append(patch_calculate)
        patch_cohort_changed.side_effect = lambda *a, **kw: calls.append(patch_cohort_changed)

        response_a = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "cohort A", "groups": [{"properties": {"team_id": 5}}]},
        )

        response_b = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}",
            data={"name": "cohort A", "groups": [{"properties": [{"key": "email", "value": "email@example.org"}]}]},
        )

        self.assertEqual(response_b.status_code, 200, response_a.json())
        self.assertEqual(patch_cohort_changed.call_count, 2)
        self.assertEqual(patch_calculate.call_count, 2)
        self.assertEqual(calls, [patch_cohort_changed, patch_calculate, patch_cohort_changed, patch_calculate])

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.chain")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cohort_dependencies_calculated(
        self,
        patch_calculate_cohort_delay,
        patch_calculate_cohort_si,
        patch_chain,
        patch_capture,
        patch_on_commit,
    ) -> None:
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

        # Update Cohort A, should trigger dependency recalculation of B, then C
        self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{response_a.json()['id']}",
            data={
                "name": "Cohort A, reloaded",
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$some_prop",
                                "type": "person",
                                "operator": "is_set",
                            }
                        ]
                    }
                ],
            },
        )

        self.assertEqual(get_total_calculation_calls(), 4)

        # Verify that all 3 cohorts (A, B, C) were included in the dependency chain to be recalculated
        si_calls = patch_calculate_cohort_si.call_args_list
        chain_cohort_ids = [call[0][0] for call in si_calls[-3:]]  # Last 3 si() calls for the chain
        expected_cohort_ids = {response_a.json()["id"], response_b.json()["id"], response_c.json()["id"]}
        self.assertEqual(set(chain_cohort_ids), expected_cohort_ids)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cannot_delete_cohort_used_in_active_feature_flag(self, patch_calculate_cohort, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}]}]},
            name="Flag using cohort",
            key="cohort-flag",
            created_by=self.user,
            active=True,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("This cohort is used in 1 active feature flag(s): Flag using cohort", response.json()["detail"])

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cannot_delete_cohort_used_in_multiple_active_feature_flags(self, patch_calculate_cohort, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}]}]},
            name="First Flag",
            key="first-flag",
            created_by=self.user,
            active=True,
        )

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}]}]},
            name="Second Flag",
            key="second-flag",
            created_by=self.user,
            active=True,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json()["detail"]
        self.assertIn("This cohort is used in 2 active feature flag(s):", detail)
        self.assertIn("First Flag", detail)
        self.assertIn("Second Flag", detail)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_can_delete_cohort_not_used_in_feature_flags(self, patch_calculate_cohort, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertTrue(cohort.deleted)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_can_delete_cohort_used_in_inactive_feature_flag(self, patch_calculate_cohort, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}]}]},
            name="Inactive Flag",
            key="inactive-flag",
            created_by=self.user,
            active=False,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertTrue(cohort.deleted)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_can_delete_cohort_used_in_deleted_feature_flag(self, patch_calculate_cohort, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}]}]},
            name="Deleted Flag",
            key="deleted-flag",
            created_by=self.user,
            active=True,
            deleted=True,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertTrue(cohort.deleted)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cannot_delete_cohort_used_in_test_account_filters(self, patch_calculate_cohort, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        # Add cohort to test_account_filters
        self.team.test_account_filters = [{"key": "id", "value": cohort_id, "type": "cohort"}]
        self.team.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "This cohort is used in 'Filter out internal and test users' for 1 environment(s):",
            response.json()["detail"],
        )
        self.assertIn(self.team.name, response.json()["detail"])

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cannot_delete_cohort_used_in_multiple_teams_test_account_filters(
        self, patch_calculate_cohort, patch_capture
    ):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        # Add cohort to test_account_filters for multiple teams
        self.team.test_account_filters = [{"key": "id", "value": cohort_id, "type": "cohort"}]
        self.team.save()

        team2 = Team.objects.create(organization=self.organization, project=self.team.project, name="Team 2")
        team2.test_account_filters = [{"key": "id", "value": cohort_id, "type": "cohort"}]
        team2.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json()["detail"]
        self.assertIn("This cohort is used in 'Filter out internal and test users' for 2 environment(s):", detail)
        self.assertIn(self.team.name, detail)
        self.assertIn(team2.name, detail)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_can_delete_cohort_not_used_in_test_account_filters(self, patch_calculate_cohort, patch_capture):
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        # Add a different cohort to test_account_filters
        other_cohort = Cohort.objects.create(
            team=self.team, name="Other Cohort", groups=[{"properties": {"team_id": 6}}]
        )
        self.team.test_account_filters = [{"key": "id", "value": other_cohort.id, "type": "cohort"}]
        self.team.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertTrue(cohort.deleted)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cannot_delete_cohort_used_in_insight(self, patch_calculate_cohort, patch_capture):
        from posthog.models.insight import Insight

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        # Create an insight that uses the cohort
        Insight.objects.create(
            team=self.team,
            name="Test Insight",
            query={"properties": [{"type": "cohort", "value": cohort_id}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("This cohort is used in 1 insight(s): Test Insight", response.json()["detail"])

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_cannot_delete_cohort_used_in_multiple_insights(self, patch_calculate_cohort, patch_capture):
        from posthog.models.insight import Insight

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        # Create multiple insights that use the cohort
        Insight.objects.create(
            team=self.team,
            name="First Insight",
            query={"properties": [{"type": "cohort", "value": cohort_id}]},
        )
        Insight.objects.create(
            team=self.team,
            name="Second Insight",
            query={"properties": [{"type": "cohort", "value": cohort_id}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json()["detail"]
        self.assertIn("This cohort is used in 2 insight(s):", detail)
        self.assertIn("First Insight", detail)
        self.assertIn("Second Insight", detail)

    @patch("posthog.api.cohort.report_user_action")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
    def test_can_delete_cohort_not_used_in_insights(self, patch_calculate_cohort, patch_capture):
        from posthog.models.insight import Insight

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts",
            data={"name": "Test Cohort", "groups": [{"properties": {"team_id": 5}}]},
        )
        cohort_id = response.json()["id"]

        # Create an insight that uses a different cohort
        other_cohort = Cohort.objects.create(
            team=self.team, name="Other Cohort", groups=[{"properties": {"team_id": 6}}]
        )
        Insight.objects.create(
            team=self.team,
            name="Test Insight",
            query={"properties": [{"type": "cohort", "value": other_cohort.id}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}",
            data={"deleted": True},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertTrue(cohort.deleted)


class TestCalculateCohortCommand(APIBaseTest):
    def test_calculate_cohort_command_success(self):
        # Create a test cohort
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort 1",
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
        )
        # Call the command
        from io import StringIO

        from django.core.management import call_command

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
        from io import StringIO

        from django.core.management import call_command

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
    with patch("django.db.transaction.on_commit", side_effect=lambda func: func()):
        return client.post(f"/api/projects/{team_id}/cohorts", {"name": name, "groups": json.dumps(groups)})


def create_cohort_ok(client: Client, team_id: int, name: str, groups: list[dict[str, Any]]):
    response = create_cohort(client=client, team_id=team_id, name=name, groups=groups)
    assert response.status_code == 201, response.content
    return response.json()


class TestCohortTypeIntegration(APIBaseTest):
    """Test cohort type determination in API endpoints"""

    def test_update_cohort_preserves_type_on_unrelated_changes(self):
        """Updating unrelated fields should not change cohort_type"""

        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            cohort_type=CohortType.BEHAVIORAL,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$pageview",
                                    "type": "behavioral",
                                    "value": BehavioralPropertyType.PERFORMED_EVENT,
                                    "negation": False,
                                    "event_type": "events",
                                    "time_value": "30",
                                    "time_interval": "day",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Update only the name (unrelated to type)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}/", {"name": "Updated Name"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        cohort.refresh_from_db()
        self.assertEqual(cohort.cohort_type, CohortType.BEHAVIORAL)  # Should remain unchanged
        self.assertEqual(response.data["cohort_type"], CohortType.BEHAVIORAL)

    def test_cohort_type_not_set_when_not_provided(self):
        """cohort_type should remain None when not provided"""

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {
                "name": "Test Cohort",
                "filters": {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"}
                        ],
                    }
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(id=response.data["id"])
        # Should be None since no explicit type was provided
        self.assertIsNone(cohort.cohort_type)
        self.assertIsNone(response.data["cohort_type"])

    def test_api_response_includes_cohort_type(self):
        """API responses should include the cohort_type field"""

        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            cohort_type=CohortType.BEHAVIORAL,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$pageview",
                                    "type": "behavioral",
                                    "value": BehavioralPropertyType.PERFORMED_EVENT,
                                    "negation": False,
                                    "event_type": "events",
                                    "time_value": "30",
                                    "time_interval": "day",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Test GET request
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/{cohort.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("cohort_type", response.data)
        self.assertEqual(response.data["cohort_type"], CohortType.BEHAVIORAL)

        # Test LIST request
        response = self.client.get(f"/api/projects/{self.team.id}/cohorts/")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data["results"]), 1)
        cohort_data = next(c for c in response.data["results"] if c["id"] == cohort.id)
        self.assertIn("cohort_type", cohort_data)
        self.assertEqual(cohort_data["cohort_type"], CohortType.BEHAVIORAL)

    def test_explicit_cohort_type_validation_success(self):
        """Should accept valid explicit cohort types"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {
                "name": "Test Cohort",
                "cohort_type": CohortType.BEHAVIORAL,
                "filters": {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": BehavioralPropertyType.PERFORMED_EVENT,
                                "negation": False,
                                "event_type": "events",
                                "time_value": "30",
                                "time_interval": "day",
                            }
                        ],
                    }
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(id=response.data["id"])
        self.assertEqual(cohort.cohort_type, CohortType.BEHAVIORAL)
        self.assertEqual(response.data["cohort_type"], CohortType.BEHAVIORAL)

    def test_explicit_cohort_type_validation_failure(self):
        """Should reject mismatched explicit cohort types"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {
                "name": "Test Cohort",
                "cohort_type": CohortType.PERSON_PROPERTY,  # Wrong type for behavioral filters
                "filters": {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": BehavioralPropertyType.PERFORMED_EVENT,
                                "negation": False,
                                "event_type": "events",
                                "time_value": "30",
                                "time_interval": "day",
                            }
                        ],
                    }
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not match the filters", str(response.data))
        self.assertIn("Expected type: 'behavioral'", str(response.data))

    def test_explicit_cohort_type_update_validation(self):
        """Should validate explicit cohort type matches filters on updates"""
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"}],
                }
            },
        )

        # Invalid update - wrong type for existing filters
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}/",
            {"cohort_type": CohortType.BEHAVIORAL},  # Wrong - filters are person_property
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("does not match the filters", str(response.data))
        self.assertIn("Expected type: 'person_property'", str(response.data))

        # Valid update - correct type for existing filters
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}/",
            {"cohort_type": CohortType.PERSON_PROPERTY},  # Correct type
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        cohort.refresh_from_db()
        self.assertEqual(cohort.cohort_type, CohortType.PERSON_PROPERTY)

        # Update both filters and type together
        response = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort.id}/",
            {
                "cohort_type": CohortType.BEHAVIORAL,  # Now matches the new behavioral filters
                "filters": {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": BehavioralPropertyType.PERFORMED_EVENT,
                                "negation": False,
                                "event_type": "events",
                                "time_value": "30",
                                "time_interval": "day",
                            }
                        ],
                    }
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        cohort.refresh_from_db()
        self.assertEqual(cohort.cohort_type, CohortType.BEHAVIORAL)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay", side_effect=calculate_cohort_from_list)
    def test_static_cohort_csv_upload_with_email_column_only(self, patch_calculate_cohort_from_list):
        """Test CSV upload with only email column using async task"""
        person1 = Person.objects.create(
            team=self.team, distinct_ids=["user123"], properties={"email": "john@example.com"}
        )
        person2 = Person.objects.create(
            team=self.team, distinct_ids=["user456"], properties={"email": "jane@example.com"}
        )

        csv = SimpleUploadedFile(
            "email_only.csv",
            str.encode(
                """email
john@example.com
jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_email_only", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

        # Verify specific persons are in the cohort
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay", side_effect=calculate_cohort_from_list)
    def test_static_cohort_csv_upload_person_id_preference_over_email(self, patch_calculate_cohort_from_list):
        """Test that person_id is preferred over email when both columns are present"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["user456"])

        # Create persons with emails that would match if email was used instead
        person_with_email1 = Person.objects.create(
            team=self.team, distinct_ids=["email_user1"], properties={"email": "john@example.com"}
        )
        person_with_email2 = Person.objects.create(
            team=self.team, distinct_ids=["email_user2"], properties={"email": "jane@example.com"}
        )

        csv = SimpleUploadedFile(
            "person_id_and_email.csv",
            str.encode(
                f"""name,person_id,email
John Doe,{person1.uuid},john@example.com
Jane Smith,{person2.uuid},jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_person_id_over_email", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

        # Verify specific persons are in the cohort (the ones matched by person_id, not email)
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)

        # Verify that persons matched by email are NOT in the cohort
        self.assertNotIn(str(person_with_email1.uuid), person_uuids_in_cohort)
        self.assertNotIn(str(person_with_email2.uuid), person_uuids_in_cohort)

    @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay", side_effect=calculate_cohort_from_list)
    def test_static_cohort_csv_upload_distinct_id_preference_over_email(self, patch_calculate_cohort_from_list):
        """Test that distinct_id is preferred over email when both columns are present"""
        person1 = Person.objects.create(team=self.team, distinct_ids=["user123"])
        person2 = Person.objects.create(team=self.team, distinct_ids=["user456"])

        # Create persons with emails that would match if email was used instead
        person_with_email1 = Person.objects.create(
            team=self.team, distinct_ids=["email_user1"], properties={"email": "john@example.com"}
        )
        person_with_email2 = Person.objects.create(
            team=self.team, distinct_ids=["email_user2"], properties={"email": "jane@example.com"}
        )

        csv = SimpleUploadedFile(
            "distinct_id_and_email.csv",
            str.encode(
                """name,distinct_id,email
John Doe,user123,john@example.com
Jane Smith,user456,jane@example.com
"""
            ),
            content_type="application/csv",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "test_distinct_id_over_email", "csv": csv, "is_static": True},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        cohort = Cohort.objects.get(pk=response.json()["id"])

        # Verify the persons were actually added to the cohort
        people_in_cohort = Person.objects.filter(cohort__id=cohort.pk)
        self.assertEqual(people_in_cohort.count(), 2)

        # Verify specific persons are in the cohort (the ones matched by distinct_id, not email)
        person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
        self.assertIn(str(person1.uuid), person_uuids_in_cohort)
        self.assertIn(str(person2.uuid), person_uuids_in_cohort)

        # Verify that persons matched by email are NOT in the cohort
        self.assertNotIn(str(person_with_email1.uuid), person_uuids_in_cohort)
        self.assertNotIn(str(person_with_email2.uuid), person_uuids_in_cohort)
