from posthog.test.base import APIBaseTest

from posthog.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob


class TestHogFlowBatchJobAPI(APIBaseTest):
    def test_create_hog_flow_batch_job(self):
        batch_job = {
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            }
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)
        assert response.status_code == 201, response.json()
        assert response.json()["status"] == "queued"
        assert response.json()["filters"] == batch_job["filters"]
        assert response.json()["created_by"]["id"] == self.user.id

        # Verify it was created in the database
        job = HogFlowBatchJob.objects.get(id=response.json()["id"])
        assert job.team_id == self.team.id
        assert job.created_by == self.user
        assert job.status == HogFlowBatchJob.State.QUEUED
        assert job.filters == batch_job["filters"]

    def test_create_hog_flow_batch_job_with_complex_filters(self):
        batch_job = {
            "filters": {
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
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)
        assert response.status_code == 201, response.json()
        assert response.json()["filters"] == batch_job["filters"]

    def test_create_hog_flow_batch_job_missing_filters(self):
        batch_job = {}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "filters",
            "code": "required",
            "detail": "This field is required.",
            "type": "validation_error",
        }

    def test_create_hog_flow_batch_job_invalid_filters(self):
        batch_job = {
            "filters": {
                "events": [{"invalid": "structure"}],
            }
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)
        assert response.status_code == 400, response.json()

    def test_cannot_list_hog_flow_batch_jobs(self):
        # Create a batch job first
        batch_job = {
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            }
        }
        self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)

        # Try to list - should fail since we only support create
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flow_batch_jobs")
        assert response.status_code == 405  # Method not allowed

    def test_cannot_retrieve_hog_flow_batch_job(self):
        # Create a batch job first
        batch_job = {
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            }
        }
        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)
        batch_job_id = create_response.json()["id"]

        # Try to retrieve - should fail since we only support create
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flow_batch_jobs/{batch_job_id}")
        assert response.status_code == 405  # Method not allowed

    def test_cannot_update_hog_flow_batch_job(self):
        # Create a batch job first
        batch_job = {
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            }
        }
        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)
        batch_job_id = create_response.json()["id"]

        # Try to update - should fail since we only support create
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flow_batch_jobs/{batch_job_id}",
            {"filters": {"events": [{"id": "custom_event", "name": "custom_event", "type": "events", "order": 0}]}},
        )
        assert response.status_code == 405  # Method not allowed

    def test_cannot_delete_hog_flow_batch_job(self):
        # Create a batch job first
        batch_job = {
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            }
        }
        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)
        batch_job_id = create_response.json()["id"]

        # Try to delete - should fail since we only support create
        response = self.client.delete(f"/api/projects/{self.team.id}/hog_flow_batch_jobs/{batch_job_id}")
        assert response.status_code == 405  # Method not allowed

    def test_status_is_readonly(self):
        batch_job = {
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            },
            "status": "active",  # Try to set status
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flow_batch_jobs", batch_job)
        assert response.status_code == 201, response.json()
        # Status should still be queued, not active
        assert response.json()["status"] == "queued"
