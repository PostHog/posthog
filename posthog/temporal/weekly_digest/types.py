from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, TypeAlias
from uuid import UUID

from pydantic import BaseModel, RootModel


@dataclass
class CommonInput:
    redis_ttl: int = 3600 * 24 * 3  # 3 days
    redis_host: str | None = None
    redis_port: int | None = None
    batch_size: int = 100


@dataclass
class Digest:
    key: str
    period_start: datetime
    period_end: datetime


@dataclass
class WeeklyDigestInput:
    dry_run: bool
    common: CommonInput = field(default_factory=CommonInput)


@dataclass
class GenerateDigestDataInput:
    digest: Digest
    common: CommonInput


@dataclass
class GenerateOrganizationDigestInput:
    batch: tuple[int, int]
    digest: Digest
    common: CommonInput


@dataclass
class SendWeeklyDigestInput:
    dry_run: bool
    digest: Digest
    common: CommonInput


@dataclass
class SendWeeklyDigestBatchInput:
    batch: tuple[int, int]
    dry_run: bool
    digest: Digest
    common: CommonInput


class DigestDashboard(BaseModel):
    name: str
    id: int


class DigestEventDefinition(BaseModel):
    name: str
    id: UUID


class DigestExperiment(BaseModel):
    name: str
    id: int
    start_date: datetime
    end_date: Optional[datetime] = None


class DigestExternalDataSource(BaseModel):
    source_type: str
    id: UUID


class DigestFeatureFlag(BaseModel):
    name: str
    id: int
    key: str


class DigestSurvey(BaseModel):
    name: str
    id: UUID
    description: str
    start_date: datetime


class DashboardList(RootModel):
    root: list[DigestDashboard]


class EventDefinitionList(RootModel):
    root: list[DigestEventDefinition]


class ExperimentList(RootModel):
    root: list[DigestExperiment]


class ExternalDataSourceList(RootModel):
    root: list[DigestExternalDataSource]


class FeatureFlagList(RootModel):
    root: list[DigestFeatureFlag]


class SurveyList(RootModel):
    root: list[DigestSurvey]


# mypy and ruff do not agree about TypeAlias
# ruff: noqa: UP040

DigestResourceType: TypeAlias = (
    type[DashboardList]
    | type[EventDefinitionList]
    | type[ExperimentList]
    | type[ExternalDataSourceList]
    | type[FeatureFlagList]
    | type[SurveyList]
)


class TeamDigest(BaseModel):
    id: int
    name: str
    dashboards: DashboardList
    event_definitions: EventDefinitionList
    experiments_launched: ExperimentList
    experiments_completed: ExperimentList
    external_data_sources: ExternalDataSourceList
    surveys_launched: SurveyList
    feature_flags: FeatureFlagList

    def is_empty(self) -> bool:
        return (
            sum(
                [
                    len(self.dashboards.root),
                    len(self.event_definitions.root),
                    len(self.experiments_launched.root),
                    len(self.experiments_completed.root),
                    len(self.external_data_sources.root),
                    len(self.surveys_launched.root),
                    len(self.feature_flags.root),
                ]
            )
            == 0
        )


class OrganizationDigest(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    team_digests: list[TeamDigest]

    def filter_for_user(self, user_teams: set[int]) -> "OrganizationDigest":
        """Returns a new OrganizationDigest with only the teams the user has access to and notifications enabled for."""
        filtered_digests = [team_digest for team_digest in self.team_digests if team_digest.id in user_teams]

        return OrganizationDigest(
            id=self.id,
            name=self.name,
            created_at=self.created_at,
            team_digests=filtered_digests,
        )

    def is_empty(self) -> bool:
        return all(digest.is_empty() for digest in self.team_digests)
