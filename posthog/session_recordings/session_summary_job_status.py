import json
from dataclasses import asdict, dataclass
from uuid import uuid4

from posthog.redis import get_client

STATUS_TTL_SECONDS = 20 * 60  # 20 minutes


@dataclass
class SummaryJobStatus:
    job_id: str
    session_id: str
    team_id: int
    status: str = "pending"  # pending, running, complete, error
    progress: str | None = None
    result: dict | None = None
    error_message: str | None = None


def _job_key(team_id: int, job_id: str) -> str:
    return f"summary_job:{team_id}:{job_id}"


def _running_key(team_id: int, session_id: str) -> str:
    return f"summary_running:{team_id}:{session_id}"


class SummaryJobStatusManager:
    def __init__(self, team_id: int, job_id: str | None = None):
        self.team_id = team_id
        self.job_id = job_id or uuid4().hex
        self.redis_client = get_client()

    def store_status(self, status: SummaryJobStatus) -> None:
        key = _job_key(self.team_id, self.job_id)
        self.redis_client.setex(key, STATUS_TTL_SECONDS, json.dumps(asdict(status)))

    def get_status(self) -> SummaryJobStatus | None:
        key = _job_key(self.team_id, self.job_id)
        raw = self.redis_client.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        return SummaryJobStatus(**data)

    def update_progress(self, progress: str) -> None:
        status = self.get_status()
        if status:
            status.progress = progress
            status.status = "running"
            self.store_status(status)

    def mark_complete(self, result: dict) -> None:
        status = self.get_status()
        if status:
            status.status = "complete"
            status.result = result
            status.progress = None
            self.store_status(status)
            self.unregister_running_session(self.team_id, status.session_id)

    def mark_error(self, error_message: str) -> None:
        status = self.get_status()
        if status:
            status.status = "error"
            status.error_message = error_message
            status.progress = None
            self.store_status(status)
            self.unregister_running_session(self.team_id, status.session_id)

    @classmethod
    def get_running_job_for_session(cls, team_id: int, session_id: str) -> str | None:
        client = get_client()
        key = _running_key(team_id, session_id)
        raw = client.get(key)
        if raw:
            return raw.decode() if isinstance(raw, bytes) else raw
        return None

    @classmethod
    def register_running_session(cls, team_id: int, session_id: str, job_id: str) -> None:
        client = get_client()
        key = _running_key(team_id, session_id)
        client.setex(key, STATUS_TTL_SECONDS, job_id)

    @classmethod
    def unregister_running_session(cls, team_id: int, session_id: str) -> None:
        client = get_client()
        key = _running_key(team_id, session_id)
        client.delete(key)
