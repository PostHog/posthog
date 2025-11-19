from uuid import UUID

from pydantic import BaseModel


class GenerateEventScreenshotsInput(BaseModel):
    team_id: int
    event_definition_id: UUID
