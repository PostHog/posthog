from uuid import UUID

from pydantic import BaseModel


class ExportRecordingInput(BaseModel):
    exported_asset_id: int


class ExportContext(BaseModel):
    export_id: UUID
    exported_asset_id: int
    session_id: str
    team_id: int
