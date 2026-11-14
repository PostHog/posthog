import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from django.db import connection
from django.test import override_settings

from parameterized import parameterized

from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.shared_activities import (
    FetchAllClusteringJobsInput,
    TeamAIConsentInput,
    check_ai_data_processing_consent_activity,
    fetch_all_clustering_jobs_activity,
)


def _create_team(approved: bool | None, enabled: bool = True) -> int:
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Org", is_ai_data_processing_approved=approved)
    from products.ai_observability.backend.models.clustering_config import ClusteringConfig

    team = Team.objects.create(organization=organization, name="Team")
    ClusteringConfig.objects.create(team=team, enabled=enabled)
    return team.id


@pytest.mark.django_db(transaction=True)
class TestCheckAIDataProcessingConsentActivity:
    @pytest.mark.asyncio
    async def test_scheduled_jobs_wait_for_the_first_run_to_finish(self) -> None:
        from products.ai_observability.backend.models.clustering_job import ClusteringJob
        from products.ai_observability.backend.models.clustering_run import ClusteringRun

        team_id = await database_sync_to_async(_create_team)(True)

        def create_run() -> str:
            job = ClusteringJob.objects.create(team_id=team_id, name="Traces", analysis_level="trace")
            ClusteringRun.objects.for_team(team_id).create(team_id=team_id, job=job, workflow_id="first-run-test")
            return str(job.id)

        job_id = await database_sync_to_async(create_run)()
        inputs = FetchAllClusteringJobsInput(team_ids=[team_id])
        assert await fetch_all_clustering_jobs_activity(inputs) == {}
        await database_sync_to_async(lambda: ClusteringRun.objects.for_team(team_id).update(status="completed"))()
        jobs = await fetch_all_clustering_jobs_activity(inputs)
        assert [job.job_id for job in jobs[team_id]] == [job_id]

    @pytest.mark.asyncio
    async def test_consent_does_not_replace_clustering_opt_in(self) -> None:
        team_id = await database_sync_to_async(_create_team)(True, False)
        assert await check_ai_data_processing_consent_activity(TeamAIConsentInput(team_id=team_id)) is False

    @parameterized.expand(
        [
            ("approved", True, True),
            ("null_is_not_approved", None, False),
            ("not_approved", False, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_consent_flag_decides(self, _name: str, approved: bool | None, expected: bool) -> None:
        team_id = await database_sync_to_async(_create_team)(approved)

        assert await check_ai_data_processing_consent_activity(TeamAIConsentInput(team_id=team_id)) is expected

    @pytest.mark.asyncio
    async def test_missing_team_is_not_approved(self) -> None:
        assert await check_ai_data_processing_consent_activity(TeamAIConsentInput(team_id=-1)) is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_consent_recovers_after_worker_connection_closes(self) -> None:
        team_id = await database_sync_to_async(_create_team)(True)
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))

        def disconnect() -> None:
            connection.ensure_connection()
            connection.connection.close()

        await asyncio.to_thread(disconnect)

        with override_settings(TEST=False):
            assert await check_ai_data_processing_consent_activity(TeamAIConsentInput(team_id=team_id)) is True
