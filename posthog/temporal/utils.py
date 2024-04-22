import dataclasses
import uuid


# Dataclass living here to avoid circular reference
@dataclasses.dataclass
class ExternalDataWorkflowInputs:
    team_id: int
    external_data_source_id: uuid.UUID
    external_data_schema_id: uuid.UUID | None = None
