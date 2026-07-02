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
class CDPProducerWorkflowInputs:
    team_id: int
    schema_id: str
    job_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "job_id": self.job_id,
        }


# Lives here (not in the warehouse_sources product) so the data_warehouse API can construct it to start
# the re-mask workflow without importing across the product boundary — same reason as the inputs above.
# The name constant keeps the `@workflow.defn` and the cross-product `start_workflow` call in sync.
REMASK_COLUMNS_WORKFLOW_NAME = "remask-warehouse-columns"


@dataclasses.dataclass
class RemaskColumnsInputs:
    team_id: int
    schema_id: uuid.UUID
    # Source column names newly added to the mask set. PK / incremental columns are filtered out again
    # inside `mask_table_columns`, so passing extras is harmless.
    columns: list[str]

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"team_id": self.team_id, "schema_id": str(self.schema_id), "columns": self.columns}
