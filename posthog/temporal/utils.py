import uuid
import typing
import dataclasses
from typing import Optional


# Dataclass living here to avoid circular reference
@dataclasses.dataclass
class ExternalDataWorkflowInputs:
    team_id: int
    external_data_source_id: uuid.UUID
    external_data_schema_id: uuid.UUID | None = None
    billable: bool = True
    reset_pipeline: Optional[bool] = None

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "external_data_source_id": self.external_data_source_id,
            "external_data_schema_id": self.external_data_schema_id,
            "billable": self.billable,
            "reset_pipeline": self.reset_pipeline,
        }


@dataclasses.dataclass
class DuckLakeCopyModelInput:
    """Metadata for a single model that needs to be copied into DuckLake."""

    model_label: str
    saved_query_id: str
    table_uri: str


@dataclasses.dataclass
class DataModelingDuckLakeCopyInputs:
    """Workflow inputs passed to DuckLakeCopyDataModelingWorkflow."""

    team_id: int
    job_id: str
    models: list[DuckLakeCopyModelInput]

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "model_labels": [model.model_label for model in self.models],
        }
