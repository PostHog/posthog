import json

from unittest.mock import patch

from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings

import requests
import responses
from celery.exceptions import Retry
from parameterized import parameterized

from posthog.models.user import User
from posthog.tasks.user_analytics_deletion import delete_user_analytics

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


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
class TestUserAnalyticsDeletionSignal(TestCase):
    @parameterized.expand([(None, "example-user", False), ("US", None, False), ("EU", "example-user", True)])
    @patch("kombu.Producer.publish")
    def test_queryset_deletion_queues_only_cloud_users_after_commit(
        self, deployment: str | None, distinct_id: str | None, queued: bool, publish
    ) -> None:
        user = User.objects.create(email="deleted@example.com", distinct_id=distinct_id)
        with override_settings(CLOUD_DEPLOYMENT=deployment), self.captureOnCommitCallbacks(execute=True):
            User.objects.filter(pk=user.pk).delete()
            assert not publish.called
        assert publish.called is queued
        if queued:
            assert publish.call_args.args[0][0] == (distinct_id,)

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("kombu.Producer.publish")
    def test_rolled_back_deletion_does_not_publish(self, publish) -> None:
        user = User.objects.create(email="retained@example.com", distinct_id="retained-user")
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            User.objects.filter(pk=user.pk).delete()
            transaction.set_rollback(True)
        assert User.objects.filter(pk=user.pk).exists()
        assert not publish.called


@override_settings(
    CLOUD_DEPLOYMENT="US",
    POSTHOG_HOST="https://us.posthog.com",
    POSTHOG_PROJECT_ID=2,
    POSTHOG_USER_DELETION_API_KEY="phs_fake_deletion_key",
)
class TestDeleteUserAnalytics(SimpleTestCase):
    @parameterized.expand(
        [
            (ACCEPTED,),
            ({**ACCEPTED, "persons_deleted": 1, "persons_queued_for_deletion": 0},),
            ({**ACCEPTED, "persons_found": 0, "persons_queued_for_deletion": 0},),
        ]
    )
    @responses.activate
    def test_requests_profile_events_and_replays(self, receipt: dict[str, object]) -> None:
        data_receipt = DATA_QUEUED if receipt["persons_found"] else receipt
        responses.post(DELETION_URL, json=data_receipt, status=202)
        responses.post(DELETION_URL, json=receipt, status=202)
        delete_user_analytics.apply(args=("example-user",), throw=True).get()
        assert len(responses.calls) == 2
        assert responses.calls[0].request.headers["Authorization"] == "Bearer phs_fake_deletion_key"
        assert [json.loads(call.request.body) for call in responses.calls] == [
            {"distinct_ids": ["example-user"], "delete_events": True, "delete_recordings": True, "keep_person": True},
            {"distinct_ids": ["example-user"], "delete_events": False, "delete_recordings": True, "keep_person": False},
        ]

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
    def test_retries_failed_or_partial_data_deletion(self, status: int, receipt: dict[str, object]) -> None:
        responses.post(DELETION_URL, json=receipt, status=status)
        responses.post(DELETION_URL, json=DATA_QUEUED, status=202)
        responses.post(DELETION_URL, json=ACCEPTED, status=202)
        assert delete_user_analytics.apply(args=("example-user",), throw=False).successful()
        assert len(responses.calls) == 3
        assert all(json.loads(call.request.body)["distinct_ids"] == ["example-user"] for call in responses.calls)

    @parameterized.expand(
        [
            ({**ACCEPTED, "persons_queued_for_deletion": 0},),
            ({**ACCEPTED, "recordings_queued_for_deletion": False},),
        ]
    )
    @responses.activate
    def test_retries_partial_profile_deletion(self, receipt: dict[str, object]) -> None:
        for result in [DATA_QUEUED, receipt, DATA_QUEUED, ACCEPTED]:
            responses.post(DELETION_URL, json=result, status=202)
        assert delete_user_analytics.apply(args=("example-user",), throw=False).successful()
        assert len(responses.calls) == 4

    @responses.activate
    def test_network_failure_retries_without_exposing_request_details(self) -> None:
        responses.post(DELETION_URL, body=requests.Timeout("sensitive request details"))
        with self.assertRaisesMessage(Retry, "request_failed") as error:
            delete_user_analytics.apply(args=("example-user",), throw=True)
        assert "sensitive request details" not in str(error.exception)

    @override_settings(POSTHOG_USER_DELETION_API_KEY="")
    @responses.activate
    def test_missing_credentials_retries_without_sending(self) -> None:
        with self.assertRaises(Retry):
            delete_user_analytics.apply(args=("example-user",), throw=True)
        assert not responses.calls
