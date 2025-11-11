from datetime import datetime
from typing import Optional, TypeAlias
from uuid import UUID

from pydantic import BaseModel, RootModel


class CommonInput(BaseModel):
    redis_ttl: int = 3600 * 24 * 3  # 3 days
    redis_host: str | None = None
    redis_port: int | None = None
    batch_size: int = 2500
    django_redis_url: str | None = None


class Digest(BaseModel):
    key: str
    period_start: datetime
    period_end: datetime

    def render_payload(self) -> dict[str, str]:
        return {
            "end_inclusive": self.period_end.isoformat(),
            "start_inclusive": self.period_start.isoformat(),
            "digest_key": self.key,
        }


class WeeklyDigestInput(BaseModel):
    dry_run: bool = False
    skip_generate: bool = False
    digest_key_override: str | None = None
    common: CommonInput = CommonInput()


class GenerateDigestDataInput(BaseModel):
    digest: Digest
    common: CommonInput


class GenerateDigestDataBatchInput(BaseModel):
    batch: tuple[int, int]
    digest: Digest
    common: CommonInput


class GenerateOrganizationDigestInput(BaseModel):
    batch: tuple[int, int]
    digest: Digest
    common: CommonInput


class SendWeeklyDigestInput(BaseModel):
    dry_run: bool
    digest: Digest
    common: CommonInput


class SendWeeklyDigestBatchInput(BaseModel):
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


class DigestFilter(BaseModel):
    name: Optional[str]
    short_id: str
    view_count: int
    recording_count: int = 0
    more_available: bool = False

    def render_payload(self) -> dict[str, str | int | bool | None]:
        return {
            "name": self.name or "Untitled",
            "count": self.recording_count,
            "has_more_available": self.more_available,
            "url_path": f"/replay/home/?filterId={self.short_id}",
        }


class DigestRecording(BaseModel):
    session_id: str
    recording_ttl: int


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


class FilterList(RootModel):
    root: list[DigestFilter]

    def order_by_recording_count(self) -> "FilterList":
        return FilterList(root=sorted(self.root, key=lambda f: f.recording_count, reverse=True))


class RecordingList(RootModel):
    root: list[DigestRecording]


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
    | type[FilterList]
    | type[RecordingList]
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
    feature_flags: FeatureFlagList
    filters: FilterList
    recordings: RecordingList
    surveys_launched: SurveyList

    def _fields(self) -> list[RootModel]:
        return [
            self.dashboards,
            self.event_definitions,
            self.experiments_launched,
            self.experiments_completed,
            self.external_data_sources,
            self.feature_flags,
            self.filters,
            self.recordings,
            self.surveys_launched,
        ]

    def is_empty(self) -> bool:
        return sum(len(f.root) for f in self._fields()) == 0

    def count_nonempty(self) -> int:
        return sum(1 if len(field.root) > 0 else 0 for field in self._fields())

    def render_payload(self) -> dict[str, str | int | dict[str, list]]:
        return {
            "team_name": self.name,
            "team_id": self.id,
            "report": {
                "new_dashboards": self.dashboards.model_dump(),
                "new_event_definitions": self.event_definitions.model_dump(),
                "new_external_data_sources": self.external_data_sources.model_dump(),
                "new_experiments_launched": self.experiments_launched.model_dump(),
                "new_experiments_completed": self.experiments_completed.model_dump(),
                "interesting_saved_filters": [f.render_payload() for f in self.filters.root],
                "new_surveys_launched": self.surveys_launched.model_dump(),
                "new_feature_flags": self.feature_flags.model_dump(),
            },
        }


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

    def count_nonempty(self) -> int:
        return sum(td.count_nonempty() for td in self.team_digests)

    def render_payload(self, digest: Digest) -> dict[str, str | list | dict[str, str] | int]:
        return {
            "organization_name": self.name,
            "organization_id": str(self.id),
            "teams": [td.render_payload() for td in self.team_digests],
            "scope": "user",
            "template_name": "weekly_digest_report",
            "period": digest.render_payload(),
            "nonempty_items": self.count_nonempty(),
        }


class PlaylistCount(BaseModel):
    session_ids: list[str] = []
    has_more: bool
    previous_ids: Optional[list[str]]
    refreshed_at: datetime
    error_count: int
    errored_at: Optional[datetime]


class ClickHouseResponse(BaseModel):
    meta: list
    data: list
    statistics: dict
    rows: int
