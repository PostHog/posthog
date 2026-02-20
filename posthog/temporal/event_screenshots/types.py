from uuid import UUID

from pydantic import BaseModel


class GenerateEventScreenshotsInput(BaseModel):
    team_id: int = 0


class EventType(BaseModel):
    event_definition_id: UUID
    name: str
    team_id: int


class EventSession(BaseModel):
    session_id: str
    url: str
    timestamp: int


class LoadEventSessionsResult(BaseModel):
    event_sessions: list[tuple[EventType, EventSession]]


class TakeEventScreenshotInput(BaseModel):
    event_type: EventType
    event_session: EventSession


class TakeEventScreenshotResult(BaseModel):
    event_type: EventType
    event_session: EventSession
    exported_asset_id: int
    content_location: str


class ClickHouseResponse(BaseModel):
    meta: list
    data: list
    statistics: dict
    rows: int
