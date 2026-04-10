from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.session_recordings.session_summary_job_status import SummaryJobStatus, SummaryJobStatusManager


class TestSummaryJobStatusManager(BaseTest):
    def _create_manager(self, job_id: str = "test-job-1") -> SummaryJobStatusManager:
        return SummaryJobStatusManager(team_id=self.team.pk, job_id=job_id)

    def _store_pending_status(self, manager: SummaryJobStatusManager, session_id: str = "session-1") -> None:
        manager.store_status(
            SummaryJobStatus(
                job_id=manager.job_id,
                session_id=session_id,
                team_id=self.team.pk,
            )
        )

    def test_mark_complete(self):
        manager = self._create_manager()
        self._store_pending_status(manager)
        SummaryJobStatusManager.register_running_session(self.team.pk, "session-1", manager.job_id)

        result = {"summary": "test summary"}
        manager.mark_complete(result)

        status = manager.get_status()
        assert status is not None
        assert status.status == "complete"
        assert status.result == result
        assert status.progress is None
        assert SummaryJobStatusManager.get_running_job_for_session(self.team.pk, "session-1") is None

    def test_mark_error(self):
        manager = self._create_manager()
        self._store_pending_status(manager)
        SummaryJobStatusManager.register_running_session(self.team.pk, "session-1", manager.job_id)

        manager.mark_error("LLM timeout")

        status = manager.get_status()
        assert status is not None
        assert status.status == "error"
        assert status.error_message == "LLM timeout"
        assert status.progress is None
        assert SummaryJobStatusManager.get_running_job_for_session(self.team.pk, "session-1") is None

    @parameterized.expand(
        [("complete", "mark_complete", {"summary": "test"}), ("error", "mark_error", "something failed")]
    )
    def test_noop_when_status_expired(self, _name: str, method: str, arg: object):
        manager = self._create_manager()
        getattr(manager, method)(arg)
