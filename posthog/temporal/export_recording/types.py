from uuid import UUID

from pydantic import BaseModel


class RedisConfig(BaseModel):
    redis_url: str | None = None  # Defaults to settings.SESSION_RECORDING_REDIS_URL
    redis_ttl: int = 3600 * 6  # 6 hours


class ExportRecordingInput(BaseModel):
    exported_recording_id: UUID
    redis_config: RedisConfig = RedisConfig()


class ExportContext(BaseModel):
    export_id: UUID
    exported_recording_id: UUID
    session_id: str
    team_id: int
    redis_config: RedisConfig
