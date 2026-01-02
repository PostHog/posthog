from unittest.mock import patch

from django.test import TestCase

from posthog.models.hog_flow.hog_flow import HogFlow
from posthog.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob
from posthog.models.user import User


class TestHogFlowBatchJob(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

        # Create a HogFlow for testing
        self.hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Test Flow",
            actions=[
                {
                    "id": "trigger_node",
                    "name": "trigger_1",
                    "type": "trigger",
                    "config": {
                        "type": "event",
                        "filters": {
                            "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                        },
                    },
                }
            ],
        )

    @patch("posthog.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation")
    def test_hog_flow_batch_job_creation(self, mock_create_invocation):
        batch_job = HogFlowBatchJob.objects.create(
            team=self.team,
            hog_flow=self.hog_flow,
            created_by=self.user,
            variables=[{"key": "event_name", "value": "$pageview"}],
        )

        assert batch_job.team == self.team
        assert batch_job.hog_flow == self.hog_flow
        assert batch_job.created_by == self.user
        assert batch_job.status == HogFlowBatchJob.State.QUEUED
        assert batch_job.variables == [{"key": "event_name", "value": "$pageview"}]
        assert str(batch_job) == f"HogFlow batch run {batch_job.id}"
        mock_create_invocation.assert_called_once()

    @patch("posthog.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation")
    def test_hog_flow_batch_job_can_fail(self, mock_create_invocation):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, variables=[])

        batch_job.status = HogFlowBatchJob.State.FAILED
        batch_job.save()
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.FAILED

    @patch("posthog.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation")
    @patch("posthog.models.hog_flow_batch_job.hog_flow_batch_job.handle_hog_flow_batch_job_created")
    def test_hog_flow_batch_job_created_signal(self, mock_handler, mock_create_invocation):
        # Disconnect the signal temporarily to test it
        from django.db.models.signals import post_save

        from posthog.models.hog_flow_batch_job.hog_flow_batch_job import handle_hog_flow_batch_job_created

        post_save.disconnect(handle_hog_flow_batch_job_created, sender=HogFlowBatchJob)

        try:
            # Reconnect with our mock
            post_save.connect(mock_handler, sender=HogFlowBatchJob)

            batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, variables=[])

            mock_handler.assert_called_once()
            call_kwargs = mock_handler.call_args[1]
            assert call_kwargs["sender"] == HogFlowBatchJob
            assert call_kwargs["instance"] == batch_job
            assert call_kwargs["created"] is True
        finally:
            # Reconnect the original signal
            post_save.disconnect(mock_handler, sender=HogFlowBatchJob)
            post_save.connect(handle_hog_flow_batch_job_created, sender=HogFlowBatchJob)

    @patch("posthog.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation")
    def test_hog_flow_batch_job_without_created_by(self, mock_create_invocation):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, variables=[])

        assert batch_job.created_by is None
        assert batch_job.team == self.team

    @patch("posthog.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation")
    def test_hog_flow_batch_job_complex_variables(self, mock_create_invocation):
        variables = [
            {"key": "first_name", "value": "John"},
            {"key": "last_name", "value": "Doe"},
            {"key": "email", "value": "john@posthog.com"},
        ]
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.hog_flow, variables=variables)

        assert batch_job.variables == variables
