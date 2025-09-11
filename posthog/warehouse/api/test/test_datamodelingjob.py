from posthog.test.base import APIBaseTest

from django.utils import timezone

from posthog.models.team.team import Team
from posthog.warehouse.models.data_modeling_job import DataModelingJob
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery


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
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("results", data)
        results = data["results"]
        self.assertEqual(len(results), 3)

        # Most recent should be first
        job_ids = [job["id"] for job in results]
        expected_ids = [str(job.id) for job in [self.job3, self.job2, self.job1]]
        self.assertEqual(job_ids, expected_ids)

        first_job = results[0]
        self.assertEqual(first_job["status"], DataModelingJob.Status.FAILED)
        self.assertEqual(first_job["saved_query_id"], str(self.saved_query.id))
        self.assertEqual(first_job["rows_materialized"], 0)
        self.assertEqual(first_job["error"], "Something went wrong")

    def test_retrieve_data_modeling_job(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/data_modeling_jobs/{self.job1.id}/")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["id"], str(self.job1.id))
        self.assertEqual(data["status"], DataModelingJob.Status.COMPLETED)
        self.assertEqual(data["rows_materialized"], 100)
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
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("results", data)
        results = data["results"]
        self.assertEqual(len(results), 3)
        self.assertNotIn(str(other_job.id), [job["id"] for job in results])

        response = self.client.get(
            f"/api/environments/{self.team.pk}/data_modeling_jobs/?saved_query_id={other_saved_query.id}"
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("results", data)
        results = data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], str(other_job.id))

    def test_cannot_access_other_teams_jobs(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/data_modeling_jobs/{self.other_team_job.id}/")
        self.assertEqual(response.status_code, 404)

        response = self.client.get(f"/api/environments/{self.team.pk}/data_modeling_jobs/")
        self.assertEqual(response.status_code, 200)

        job_ids = [job["id"] for job in response.json()["results"]]
        self.assertNotIn(str(self.other_team_job.id), job_ids)
