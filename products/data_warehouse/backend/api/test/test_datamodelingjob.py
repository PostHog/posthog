from posthog.test.base import APIBaseTest

from django.utils import timezone

from posthog.models.team.team import Team

from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class TestDataModelingJob(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization)
        self.saved_query = DataWarehouseSavedQuery.objects.create(team=self.team, name="Test saved query")
        self.other_team_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.other_team, name="Other team saved query"
        )

        self.job1 = DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.COMPLETED,
            rows_materialized=100,
            last_run_at=timezone.now(),
        )

        self.job2 = DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.RUNNING,
            rows_materialized=50,
            last_run_at=timezone.now(),
        )

        self.job3 = DataModelingJob.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            status=DataModelingJob.Status.FAILED,
            rows_materialized=0,
            error="Something went wrong",
            last_run_at=timezone.now(),
        )

        # Another team's job
        self.other_team_job = DataModelingJob.objects.create(
            team=self.other_team,
            saved_query=self.other_team_saved_query,
            status=DataModelingJob.Status.COMPLETED,
            rows_materialized=200,
            last_run_at=timezone.now(),
        )

    def test_list_data_modeling_jobs(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/data_modeling_jobs/")
        assert response.status_code == 200

        data = response.json()
        assert "results" in data
        results = data["results"]
        assert len(results) == 3

        # Most recent should be first
        job_ids = [job["id"] for job in results]
        expected_ids = [str(job.id) for job in [self.job3, self.job2, self.job1]]
        assert job_ids == expected_ids

        first_job = results[0]
        assert first_job["status"] == DataModelingJob.Status.FAILED
        assert first_job["saved_query_id"] == str(self.saved_query.id)
        assert first_job["rows_materialized"] == 0
        assert first_job["error"] == "Something went wrong"

    def test_retrieve_data_modeling_job(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/data_modeling_jobs/{self.job1.id}/")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == str(self.job1.id)
        assert data["status"] == DataModelingJob.Status.COMPLETED
        assert data["rows_materialized"] == 100
        other_saved_query = DataWarehouseSavedQuery.objects.create(team=self.team, name="Another saved query")
        other_job = DataModelingJob.objects.create(
            team=self.team,
            saved_query=other_saved_query,
            status=DataModelingJob.Status.COMPLETED,
            rows_materialized=75,
            last_run_at=timezone.now(),
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/data_modeling_jobs/?saved_query_id={self.saved_query.id}"
        )
        assert response.status_code == 200

        data = response.json()
        assert "results" in data
        results = data["results"]
        assert len(results) == 3
        assert str(other_job.id) not in [job["id"] for job in results]

        response = self.client.get(
            f"/api/environments/{self.team.pk}/data_modeling_jobs/?saved_query_id={other_saved_query.id}"
        )
        assert response.status_code == 200

        data = response.json()
        assert "results" in data
        results = data["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(other_job.id)

    def test_cannot_access_other_teams_jobs(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/data_modeling_jobs/{self.other_team_job.id}/")
        assert response.status_code == 404

        response = self.client.get(f"/api/environments/{self.team.pk}/data_modeling_jobs/")
        assert response.status_code == 200

        job_ids = [job["id"] for job in response.json()["results"]]
        assert str(self.other_team_job.id) not in job_ids
