from pathlib import Path

from pydantic import BaseModel


class ExportRecordingInput(BaseModel):
    exported_asset_id: int


class ExportContext(BaseModel):
    session_id: str
    team_id: int


class ExportData(BaseModel):
    export_context: ExportContext
    clickhouse_rows: Path
    recording_data: list[Path]
