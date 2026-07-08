import typing
import dataclasses


@dataclasses.dataclass
class TeamDataActivityInputs:
    """Inputs shared by the per-domain team-data deletion activities."""

    team_ids: list[int]
    user_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"team_ids": self.team_ids, "user_id": self.user_id}


@dataclasses.dataclass
class ProjectRecordInputs:
    project_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"project_id": self.project_id}


@dataclasses.dataclass
class OrganizationRecordInputs:
    organization_id: str
    user_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"organization_id": self.organization_id, "user_id": self.user_id}


@dataclasses.dataclass
class ProjectEmailInputs:
    user_id: int
    project_name: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"user_id": self.user_id}


@dataclasses.dataclass
class OrganizationEmailInputs:
    user_id: int
    organization_name: str
    project_names: list[str]

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"user_id": self.user_id}


@dataclasses.dataclass
class DeleteTeamsDataWorkflowInputs:
    """Inputs for the reusable core ``DeleteTeamsDataWorkflow``."""

    team_ids: list[int]
    user_id: int

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"team_ids": self.team_ids, "user_id": self.user_id}


@dataclasses.dataclass
class DeleteProjectDataWorkflowInputs:
    """Inputs for ``DeleteProjectDataWorkflow`` (project or environment-only deletion)."""

    team_ids: list[int]
    project_id: int | None
    user_id: int
    project_name: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"team_ids": self.team_ids, "project_id": self.project_id, "user_id": self.user_id}


@dataclasses.dataclass
class DeleteOrganizationWorkflowInputs:
    """Inputs for ``DeleteOrganizationWorkflow``."""

    team_ids: list[int]
    organization_id: str
    user_id: int
    organization_name: str
    project_names: list[str]

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"team_ids": self.team_ids, "organization_id": self.organization_id, "user_id": self.user_id}
