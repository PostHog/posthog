import typing
import dataclasses


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
