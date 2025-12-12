from uuid import UUID

from pydantic import BaseModel


class ExportRecordingInput(BaseModel):
    exported_recording_id: UUID


class ExportContext(BaseModel):
    export_id: UUID
    exported_recording_id: UUID
    session_id: str
    team_id: int
