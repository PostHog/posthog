from unittest.mock import patch

from django.test import TestCase

from posthog.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob
from posthog.models.user import User


class TestHogFlowBatchJob(TestCase):
    def setUp(self):
        super().setUp()
        org, team, user = User.objects.bootstrap("Test org", "ben@posthog.com", None)
        self.team = team
        self.user = user
        self.org = org

    def test_hog_flow_batch_job_creation(self):
        batch_job = HogFlowBatchJob.objects.create(
            team=self.team,
            created_by=self.user,
            filters={"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
        )

        assert batch_job.team == self.team
        assert batch_job.created_by == self.user
        assert batch_job.status == HogFlowBatchJob.State.QUEUED
        assert batch_job.filters == {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]}
        assert str(batch_job) == f"HogFlow batch run {batch_job.id}"

    def test_hog_flow_batch_job_default_status(self):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, filters={})

        assert batch_job.status == HogFlowBatchJob.State.QUEUED

    def test_hog_flow_batch_job_state_transitions(self):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, filters={})

        # Transition to active
        batch_job.status = HogFlowBatchJob.State.ACTIVE
        batch_job.save()
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.ACTIVE

        # Transition to completed
        batch_job.status = HogFlowBatchJob.State.COMPLETED
        batch_job.save()
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.COMPLETED

    def test_hog_flow_batch_job_can_be_cancelled(self):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, filters={})

        batch_job.status = HogFlowBatchJob.State.CANCELLED
        batch_job.save()
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.CANCELLED

    def test_hog_flow_batch_job_can_fail(self):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, filters={})

        batch_job.status = HogFlowBatchJob.State.FAILED
        batch_job.save()
        batch_job.refresh_from_db()
        assert batch_job.status == HogFlowBatchJob.State.FAILED

    @patch("posthog.models.hog_flow_batch_job.hog_flow_batch_job.handle_hog_flow_batch_job_created")
    def test_hog_flow_batch_job_created_signal(self, mock_handler):
        # Disconnect the signal temporarily to test it
        from django.db.models.signals import post_save

        from posthog.models.hog_flow_batch_job.hog_flow_batch_job import handle_hog_flow_batch_job_created

        post_save.disconnect(handle_hog_flow_batch_job_created, sender=HogFlowBatchJob)

        try:
            # Reconnect with our mock
            post_save.connect(mock_handler, sender=HogFlowBatchJob)

            batch_job = HogFlowBatchJob.objects.create(team=self.team, filters={})

            mock_handler.assert_called_once()
            call_kwargs = mock_handler.call_args[1]
            assert call_kwargs["sender"] == HogFlowBatchJob
            assert call_kwargs["instance"] == batch_job
            assert call_kwargs["created"] is True
        finally:
            # Reconnect the original signal
            post_save.disconnect(mock_handler, sender=HogFlowBatchJob)
            post_save.connect(handle_hog_flow_batch_job_created, sender=HogFlowBatchJob)

    def test_hog_flow_batch_job_without_created_by(self):
        batch_job = HogFlowBatchJob.objects.create(team=self.team, filters={})

        assert batch_job.created_by is None
        assert batch_job.team == self.team

    def test_hog_flow_batch_job_complex_filters(self):
        filters = {
            "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            "properties": [
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "icontains",
                    "type": "person",
                }
            ],
        }
        batch_job = HogFlowBatchJob.objects.create(team=self.team, filters=filters)

        assert batch_job.filters == filters
