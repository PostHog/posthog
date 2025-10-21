import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
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
