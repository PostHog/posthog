import json

from django.db import transaction
from django.test import TestCase, override_settings

import requests
import responses
from parameterized import parameterized

from posthog.models.user import User

PREFERENCES_URL = "https://us.posthog.com/api/projects/2/messaging/preferences/"
DELETION_URL = "https://us.posthog.com/api/projects/2/persons/bulk_delete/"


@override_settings(
    CLOUD_DEPLOYMENT="US",
    POSTHOG_HOST="https://us.posthog.com",
    POSTHOG_PROJECT_ID=2,
    POSTHOG_USER_DELETION_API_KEY="phs_fake_deletion_key",
)
class TestUserAnalyticsDeletion(TestCase):
    @parameterized.expand([(None, "example-user"), ("US", None)])
    @responses.activate
    def test_skips_users_without_cloud_analytics(self, deployment: str | None, distinct_id: str | None) -> None:
        user = User.objects.create(email="deleted@example.com", distinct_id=distinct_id)
        with override_settings(CLOUD_DEPLOYMENT=deployment), self.captureOnCommitCallbacks(execute=True):
            user.delete()
        assert not responses.calls

    @responses.activate
    def test_rolled_back_deletion_does_not_send(self) -> None:
        user = User.objects.create(email="retained@example.com", distinct_id="retained-user")
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            User.objects.filter(pk=user.pk).delete()
            transaction.set_rollback(True)
        assert User.objects.filter(pk=user.pk).exists()
        assert not responses.calls

    @parameterized.expand([("http",), ("timeout",), ("partial",), ("credentials",), ("insecure_host",)])
    @responses.activate
    def test_failure_is_logged_without_preventing_account_deletion(self, failure: str) -> None:
        user = User.objects.create(email="deleted@example.com", distinct_id="example-user")
        user_id = user.pk
        responses.post(PREFERENCES_URL, json={})
        if failure == "timeout":
            responses.post(DELETION_URL, body=requests.Timeout("sensitive request details"))
        else:
            responses.post(
                DELETION_URL,
                status=503 if failure == "http" else 202,
                json={"deletion_errors": [{"step": "profile"}]} if failure == "partial" else {},
            )
        with override_settings(
            POSTHOG_USER_DELETION_API_KEY="" if failure == "credentials" else "phs_fake_deletion_key",
            POSTHOG_HOST="http://us.posthog.com" if failure == "insecure_host" else "https://us.posthog.com",
        ):
            with self.assertLogs("posthog.user_analytics_deletion", level="ERROR") as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    User.objects.filter(pk=user.pk).delete()
        assert not User.objects.filter(pk=user_id).exists()
        assert len(responses.calls) == (0 if failure in ("credentials", "insecure_host") else 2)
        assert "sensitive request details" not in str(logs.output)
        assert "phs_fake_deletion_key" not in str(logs.output)

    @parameterized.expand([("US", "example-user"), ("EU", "example-user")])
    @responses.activate
    def test_opts_out_before_deleting_analytics(self, deployment: str, distinct_id: str) -> None:
        responses.post(PREFERENCES_URL, json={})
        responses.post(DELETION_URL, json={}, status=202)
        user = User.objects.create(email="deleted@example.com", distinct_id=distinct_id)
        with override_settings(CLOUD_DEPLOYMENT=deployment), self.captureOnCommitCallbacks(execute=True):
            user.delete()
            assert not responses.calls
        assert responses.calls[0].request.url == PREFERENCES_URL
        assert json.loads(responses.calls[0].request.body) == {"identifier": user.email, "all_marketing": False}
        assert len(responses.calls) == 2
        for call in responses.calls:
            assert call.request.headers["Authorization"] == "Bearer phs_fake_deletion_key"
        assert responses.calls[1].request.url == DELETION_URL
        assert json.loads(responses.calls[1].request.body) == {
            "distinct_ids": [distinct_id],
            "delete_events": True,
            "delete_recordings": True,
        }

    @parameterized.expand([("http",), ("timeout",)])
    @responses.activate
    def test_opt_out_failure_still_requests_analytics_and_account_deletion(self, failure: str) -> None:
        user = User.objects.create(email="deleted@example.com", distinct_id="example-user")
        user_id = user.pk
        responses.post(DELETION_URL, json={}, status=202)
        if failure == "timeout":
            responses.post(PREFERENCES_URL, body=requests.Timeout("sensitive request details"))
        else:
            responses.post(PREFERENCES_URL, status=403)
        with self.assertLogs("posthog.user_analytics_deletion", level="ERROR") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                user.delete()
        assert not User.objects.filter(pk=user_id).exists()
        assert len(responses.calls) == 2
        assert responses.calls[0].request.url == PREFERENCES_URL
        assert responses.calls[1].request.url == DELETION_URL
        assert json.loads(responses.calls[1].request.body) == {
            "distinct_ids": ["example-user"],
            "delete_events": True,
            "delete_recordings": True,
        }
        assert "sensitive request details" not in str(logs.output)
        assert user.email not in str(logs.output)
