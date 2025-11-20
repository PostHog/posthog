from pydantic import BaseModel


class GenerateEventScreenshotsInput(BaseModel):
    team_id: int = 0


class EventType(BaseModel):
    name: str
    team_id: int


class EventSession(BaseModel):
    session_id: str
    url: str
    timestamp: int


class LoadEventSessionsResult(BaseModel):
    event_sessions: list[tuple[EventType, EventSession]]


class ClickHouseResponse(BaseModel):
    meta: list
    data: list
    statistics: dict
    rows: int
