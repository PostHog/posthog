import json
from datetime import timedelta

import time_machine
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

import requests
import responses
from parameterized import parameterized

from posthog.models.user import User
from posthog.models.user_analytics_deletion import UserAnalyticsDeletion
from posthog.tasks.user_analytics_deletion import UserAnalyticsDeletionFailed, process_user_analytics_deletions

DELETION_URL = "https://us.posthog.com/api/projects/2/persons/bulk_delete/"
ACCEPTED = {
    "persons_found": 1,
    "persons_deleted": 0,
    "persons_queued_for_deletion": 1,
    "events_queued_for_deletion": True,
    "recordings_queued_for_deletion": True,
    "deletion_errors": [],
}
DATA_QUEUED = {**ACCEPTED, "persons_queued_for_deletion": 0}


@override_settings(
    CLOUD_DEPLOYMENT="US",
    POSTHOG_HOST="https://us.posthog.com",
    POSTHOG_PROJECT_ID=2,
    POSTHOG_USER_DELETION_API_KEY="phx_fake_deletion_key",
)
class TestUserAnalyticsDeletion(TestCase):
    @parameterized.expand([(None, "example-user", False), ("US", None, False), ("EU", "example-user", True)])
    def test_deletion_only_queues_cloud_users_with_an_identity(
        self, deployment: str | None, distinct_id: str | None, queued: bool
    ) -> None:
        user = User.objects.create(email="deleted@example.com", distinct_id=distinct_id)
        with override_settings(CLOUD_DEPLOYMENT=deployment):
            User.objects.filter(pk=user.pk).delete()
        assert UserAnalyticsDeletion.objects.exists() is queued
        if queued:
            assert UserAnalyticsDeletion.objects.get().distinct_id == distinct_id

    def test_rolled_back_account_deletion_does_not_queue_analytics_deletion(self) -> None:
        user = User.objects.create(email="retained@example.com", distinct_id="retained-user")
        with transaction.atomic():
            User.objects.filter(pk=user.pk).delete()
            assert UserAnalyticsDeletion.objects.filter(distinct_id=user.distinct_id).exists()
            transaction.set_rollback(True)
        assert User.objects.filter(pk=user.pk).exists()
        assert not UserAnalyticsDeletion.objects.exists()

    @parameterized.expand(
        [
            (ACCEPTED,),
            ({**ACCEPTED, "persons_deleted": 1, "persons_queued_for_deletion": 0},),
            (
                {
                    **ACCEPTED,
                    "persons_found": 0,
                    "persons_queued_for_deletion": 0,
                    "events_queued_for_deletion": False,
                    "recordings_queued_for_deletion": False,
                },
            ),
        ]
    )
    @responses.activate
    def test_account_deletion_requests_all_analytics_data_after_grace_period(self, receipt: dict[str, object]) -> None:
        with time_machine.travel("2026-01-01T00:00:00Z", tick=False):
            user = User.objects.create(email="deleted@example.com", distinct_id="example-user")
            user.delete()
            process_user_analytics_deletions()
            assert not responses.calls
            assert UserAnalyticsDeletion.objects.exists()

        data_receipt = DATA_QUEUED if receipt["persons_found"] else receipt
        responses.post(DELETION_URL, json=data_receipt, status=202)
        responses.post(DELETION_URL, json=receipt, status=202)
        with time_machine.travel("2026-01-01T01:01:00Z", tick=False):
            process_user_analytics_deletions()
        assert len(responses.calls) == 2
        request = responses.calls[0].request
        assert request.headers["Authorization"] == "Bearer phx_fake_deletion_key"
        assert json.loads(request.body) == {
            "distinct_ids": ["example-user"],
            "delete_events": True,
            "delete_recordings": True,
            "keep_person": True,
        }
        assert json.loads(responses.calls[1].request.body) == {
            "distinct_ids": ["example-user"],
            "delete_events": False,
            "delete_recordings": True,
            "keep_person": False,
        }
        assert not UserAnalyticsDeletion.objects.exists()

    @parameterized.expand(
        [
            (503, {}),
            (429, {}),
            (401, {}),
            (202, {}),
            (202, {**DATA_QUEUED, "deletion_errors": [{"step": "queue_recording_deletion"}]}),
            (202, {**DATA_QUEUED, "events_queued_for_deletion": False}),
            (202, {**DATA_QUEUED, "recordings_queued_for_deletion": False}),
        ]
    )
    @responses.activate
    def test_failed_or_partial_requests_survive_until_a_later_sweep(
        self, status: int, receipt: dict[str, object]
    ) -> None:
        with time_machine.travel("2026-01-01T00:00:00Z", tick=False):
            deletion = UserAnalyticsDeletion.objects.create(distinct_id="example-user", next_attempt_at=timezone.now())
            responses.post(DELETION_URL, json=receipt, status=status)
            with self.assertRaises(UserAnalyticsDeletionFailed):
                process_user_analytics_deletions()
            deletion.refresh_from_db()
            assert deletion.next_attempt_at == timezone.now() + timedelta(hours=1)
            process_user_analytics_deletions()
            assert len(responses.calls) == 1

        responses.post(DELETION_URL, json=DATA_QUEUED, status=202)
        responses.post(DELETION_URL, json=ACCEPTED, status=202)
        with time_machine.travel("2026-01-01T01:01:00Z", tick=False):
            process_user_analytics_deletions()
        assert not UserAnalyticsDeletion.objects.exists()

    @parameterized.expand(
        [
            ({**ACCEPTED, "persons_queued_for_deletion": 0},),
            ({**ACCEPTED, "recordings_queued_for_deletion": False},),
        ]
    )
    @responses.activate
    def test_failed_profile_deletion_keeps_request_after_data_was_queued(self, receipt: dict[str, object]) -> None:
        UserAnalyticsDeletion.objects.create(distinct_id="example-user", next_attempt_at=timezone.now())
        responses.post(DELETION_URL, json=DATA_QUEUED, status=202)
        responses.post(DELETION_URL, json=receipt, status=202)
        with self.assertRaisesMessage(UserAnalyticsDeletionFailed, "incomplete_deletion"):
            process_user_analytics_deletions()
        assert len(responses.calls) == 2
        assert UserAnalyticsDeletion.objects.exists()

    @responses.activate
    def test_network_failure_keeps_request_without_exposing_credentials(self) -> None:
        UserAnalyticsDeletion.objects.create(distinct_id="example-user", next_attempt_at=timezone.now())
        responses.post(DELETION_URL, body=requests.Timeout("sensitive request details"))
        with self.assertRaisesMessage(UserAnalyticsDeletionFailed, "request_failed"):
            process_user_analytics_deletions()
        assert UserAnalyticsDeletion.objects.exists()

    @override_settings(POSTHOG_USER_DELETION_API_KEY="")
    def test_missing_credentials_leave_requests_pending(self) -> None:
        deletion = UserAnalyticsDeletion.objects.create(distinct_id="example-user", next_attempt_at=timezone.now())
        with self.assertRaises(ImproperlyConfigured), patch("requests.post") as post:
            process_user_analytics_deletions()
        assert not post.called
        deletion.refresh_from_db()
        assert deletion.next_attempt_at <= timezone.now()
