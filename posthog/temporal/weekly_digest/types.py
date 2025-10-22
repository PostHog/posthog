import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Self
from uuid import UUID

from pydantic import BaseModel


@dataclass(frozen=True)
class WeeklyDigestInput:
    dry_run: bool
    redis_ttl: int = 3600 * 24 * 3  # 3 days
    redis_host: str = os.getenv("WEEKLY_DIGEST_REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("WEEKLY_DIGEST_REDIS_PORT", "6379"))


@dataclass(frozen=True)
class GenerateDigestDataInput:
    digest_key: str
    period_start: datetime
    period_end: datetime
    redis_ttl: int
    redis_host: str = os.getenv("WEEKLY_DIGEST_REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("WEEKLY_DIGEST_REDIS_PORT", "6379"))
    batch_size: int = 100


@dataclass(frozen=True)
class GenerateOrganizationDigestInput:
    batch: tuple[int, int]
    digest_key: str
    redis_ttl: int
    redis_host: str = os.getenv("WEEKLY_DIGEST_REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("WEEKLY_DIGEST_REDIS_PORT", "6379"))


@dataclass(frozen=True)
class SendWeeklyDigestInput:
    dry_run: bool
    digest_key: str
    period_start: datetime
    period_end: datetime
    redis_host: str = os.getenv("WEEKLY_DIGEST_REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("WEEKLY_DIGEST_REDIS_PORT", "6379"))
    batch_size: int = 100


@dataclass(frozen=True)
class SendWeeklyDigestBatchInput:
    dry_run: bool
    batch: tuple[int, int]
    digest_key: str
    period_start: datetime
    period_end: datetime
    redis_host: str = os.getenv("WEEKLY_DIGEST_REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("WEEKLY_DIGEST_REDIS_PORT", "6379"))


class DigestDashboard(BaseModel):
    name: str
    id: int


class DashboardList(BaseModel):
    dashboards: list[DigestDashboard]


class DigestEventDefinition(BaseModel):
    name: str
    id: UUID


class EventDefinitionList(BaseModel):
    definitions: list[DigestEventDefinition]


class DigestExperiment(BaseModel):
    name: str
    id: int
    start_date: datetime
    end_date: Optional[datetime] = None


class ExperimentList(BaseModel):
    experiments: list[DigestExperiment]


class DigestExternalDataSource(BaseModel):
    source_type: str
    id: UUID


class ExternalDataSourceList(BaseModel):
    sources: list[DigestExternalDataSource]


class DigestSurvey(BaseModel):
    name: str
    id: UUID
    description: str
    start_date: datetime


class SurveyList(BaseModel):
    surveys: list[DigestSurvey]


class DigestFeatureFlag(BaseModel):
    name: str
    id: int
    key: str


class FeatureFlagList(BaseModel):
    flags: list[DigestFeatureFlag]


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
                    len(self.dashboards.dashboards),
                    len(self.event_definitions.definitions),
                    len(self.experiments_launched.experiments),
                    len(self.experiments_completed.experiments),
                    len(self.external_data_sources.sources),
                    len(self.surveys_launched.surveys),
                    len(self.feature_flags.flags),
                ]
            )
            == 0
        )


class OrganizationDigest(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    team_digests: list[TeamDigest]

    def filter_for_user(self, user_teams: set[int]) -> Self:
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
