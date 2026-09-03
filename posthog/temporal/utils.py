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


@dataclasses.dataclass(frozen=True)
class CDPProducerWorkflowInputs:
    """Which staged run to produce to Kafka.

    Exactly one of `schema_id` (a source sync) or `saved_query_id` (a materialized view) is set.
    Both are optional and defaulted so payloads written by an older worker stay decodable.
    """

    team_id: int
    job_id: str
    schema_id: str | None = None
    saved_query_id: str | None = None

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "saved_query_id": self.saved_query_id,
            "job_id": self.job_id,
        }
