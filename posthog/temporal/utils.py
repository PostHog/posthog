import dataclasses
import uuid
from typing import Optional


# Dataclass living here to avoid circular reference
@dataclasses.dataclass
class ExternalDataWorkflowInputs:
    team_id: int
    external_data_source_id: uuid.UUID
    external_data_schema_id: uuid.UUID | None = None
    billable: bool = True
    reset_pipeline: Optional[bool] = None

    def properties_to_log(self) -> list[str]:
        return ["team_id", "external_data_source_id", "external_data_schema_id", "billable", "reset_pipeline"]
