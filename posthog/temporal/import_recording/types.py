from uuid import UUID

from pydantic import BaseModel


class ImportRecordingInput(BaseModel):
    team_id: int
    export_file: str


class ImportContext(BaseModel):
    team_id: int
    import_id: UUID
    s3_prefix: str
    session_id: str
