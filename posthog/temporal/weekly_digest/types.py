from datetime import datetime
from typing import Literal, Optional, TypeAlias
from uuid import UUID

from pydantic import BaseModel, RootModel, field_validator

from posthog.utils import compact_number, get_instance_region


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
    allow_already_sent: bool = False
    common: CommonInput = CommonInput()


class GenerateDigestDataInput(BaseModel):
    digest: Digest
    common: CommonInput


class TeamIdRange(BaseModel):
    """A half-open [start, end) range of team ids."""

    start: int
    end: int


class GenerateDigestDataBatchInput(BaseModel):
    team_id_range: TeamIdRange
    digest: Digest
    common: CommonInput


class GenerateOrganizationDigestInput(BaseModel):
    batch: tuple[int, int]
    digest: Digest
    common: CommonInput


class SendWeeklyDigestInput(BaseModel):
    dry_run: bool
    allow_already_sent: bool
    digest: Digest
    common: CommonInput


class SendWeeklyDigestBatchInput(BaseModel):
    batch: tuple[int, int]
    dry_run: bool
    allow_already_sent: bool
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


class DigestSurvey(BaseModel):
    name: str
    id: UUID
    description: str
    start_date: datetime


# Keeps a day with any activity visible as a sliver next to a much busier day.
SPARKLINE_MIN_VISIBLE_PERCENT = 5

# Issue descriptions are exception messages of any length. The email shows one line of it.
ERROR_ISSUE_DESCRIPTION_MAX_LENGTH = 140


def render_sparkline(daily_counts: list[int]) -> list[dict[str, int]]:
    peak = max(daily_counts, default=0)
    bars = []
    for count in daily_counts:
        height_percent = round(count * 100 / peak) if peak else 0
        if count > 0:
            height_percent = max(height_percent, SPARKLINE_MIN_VISIBLE_PERCENT)
        bars.append({"count": count, "height_percent": height_percent})
    return bars


def _single_line(text: str | None, max_length: int) -> str | None:
    if not text:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 1].rstrip() + "…"


class DigestErrorIssue(BaseModel):
    name: str = "Untitled issue"
    id: UUID
    description: str | None = None
    # None when the counts could not be queried.
    occurrence_count: int | None = None
    sparkline: list[dict[str, int]] = []

    @field_validator("name", mode="before")
    @classmethod
    def _default_name(cls, value: str | None) -> str:
        return value or "Untitled issue"

    def render_payload(self) -> dict[str, str | int | list | None]:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": _single_line(self.description, ERROR_ISSUE_DESCRIPTION_MAX_LENGTH),
            "occurrence_count": self.occurrence_count,
            "occurrence_count_display": (
                compact_number(self.occurrence_count) if self.occurrence_count is not None else None
            ),
            "sparkline": self.sparkline,
        }


class UsageTrendMetric(BaseModel):
    label: str  # e.g. "Events", "Active users"
    current: int
    previous: Optional[int] = None
    change_pct: int = 0  # absolute rounded percentage; 0 when no meaningful comparison
    direction: Literal["up", "down", "flat"] = "flat"
    # False when there was no previous-week activity to compare against, so the template
    # can render "new" instead of conflating 0 -> N growth with "no change".
    has_baseline: bool = True
    daily: list[int] = []

    def render_payload(self) -> dict[str, str | int | bool | list | None]:
        return {
            **self.model_dump(exclude={"daily"}),
            # The email template (Liquid) has no number formatting filter.
            "current_display": compact_number(self.current),
            "sparkline": render_sparkline(self.daily),
        }


class UsageTrends(BaseModel):
    metrics: list[UsageTrendMetric] = []

    def render_payload(self) -> dict[str, list]:
        return {"metrics": [metric.render_payload() for metric in self.metrics]}


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


class RecordingCount(BaseModel):
    recording_count: int


class SurveyList(RootModel):
    root: list[DigestSurvey]


class ErrorIssueList(RootModel):
    root: list[DigestErrorIssue]

    def render_payload(self) -> list[dict]:
        return [issue.render_payload() for issue in self.root]


# Shown when the campaign carries no hand-written promo copy. Mirrors the nav card's
# DEFAULT_PRODUCT_PUSH_DISPLAY tagline so both surfaces say the same thing.
DEFAULT_PRODUCT_SUGGESTION_TEXT = "We think your organization would get a lot out of this product. Give it a try!"


class DigestProductSuggestion(BaseModel):
    team_id: int
    product_path: str  # This is the product name (e.g., "Product analytics")
    reason_text: str | None

    def get_readable_reason_text(self) -> str:
        """Returns human-readable suggestion copy for email interpolation."""
        return self.reason_text or DEFAULT_PRODUCT_SUGGESTION_TEXT


# mypy and ruff do not agree about TypeAlias
# ruff: noqa: UP040

DigestResourceType: TypeAlias = (
    type[DashboardList]
    | type[EventDefinitionList]
    | type[ExperimentList]
    | type[ExternalDataSourceList]
    | type[FeatureFlagList]
    | type[FilterList]
    | type[SurveyList]
    | type[ErrorIssueList]
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
    expiring_recordings: RecordingCount
    surveys_launched: SurveyList
    # New signals. Defaults keep older callers/tests constructing TeamDigest working.
    usage_trends: UsageTrends = UsageTrends()
    error_issues: ErrorIssueList = ErrorIssueList(root=[])

    def _fields(self) -> list[RootModel]:
        # NOTE: usage_trends is intentionally excluded — it is ambient context (present
        # for nearly every active team), so counting it would make almost every org
        # cross DIGEST_ITEM_COUNT_THRESHOLD and receive an email. error_issues IS counted:
        # a new production error is worth an email on its own.
        return [
            self.dashboards,
            self.event_definitions,
            self.experiments_launched,
            self.experiments_completed,
            self.external_data_sources,
            self.feature_flags,
            self.filters,
            self.surveys_launched,
            self.error_issues,
        ]

    def is_empty(self) -> bool:
        return self.count_items() == 0

    def count_items(self) -> int:
        return sum(len(f.root) for f in self._fields())

    def render_payload(
        self,
        product_suggestion: "DigestProductSuggestion | None" = None,
        event_definitions_limit: int | None = None,
    ) -> dict[str, str | int | dict[str, list | dict | int]]:
        # A project can create thousands of events in a week, and the email lists only the first few.
        # The count carries the rest, so a limited payload still renders the same email.
        event_definitions = self.event_definitions.model_dump()
        if event_definitions_limit is not None:
            event_definitions = event_definitions[:event_definitions_limit]
        report: dict[str, list | dict | int] = {
            "new_dashboards": self.dashboards.model_dump(),
            "new_event_definitions": event_definitions,
            "new_event_definitions_count": len(self.event_definitions.root),
            "new_experiments_launched": self.experiments_launched.model_dump(),
            "new_experiments_completed": self.experiments_completed.model_dump(),
            "new_external_data_sources": self.external_data_sources.model_dump(),
            "new_feature_flags": self.feature_flags.model_dump(),
            "interesting_saved_filters": [f.render_payload() for f in self.filters.root],
            "expiring_recordings": self.expiring_recordings.model_dump(),
            "new_surveys_launched": self.surveys_launched.model_dump(),
            "usage_trends": self.usage_trends.render_payload(),
            "new_error_issues": self.error_issues.render_payload(),
        }

        if product_suggestion:
            report["new_product_suggestion"] = {
                "product_path": product_suggestion.product_path,
                "reason_text": product_suggestion.get_readable_reason_text(),
            }

        return {
            "team_name": self.name,
            "team_id": self.id,
            "report": report,
        }


class UserDigestContext(BaseModel):
    """
    Container for all user-specific data in the digest.

    Add new user-specific fields here - they'll automatically be available
    in UserSpecificDigest without changing the for_user() signature.
    """

    product_suggestion: DigestProductSuggestion | None = None


class OrganizationDigest(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    team_digests: list[TeamDigest]

    def for_user(
        self,
        user_teams: set[int],
        context: "UserDigestContext | None" = None,
    ) -> "UserSpecificDigest":
        """Returns a UserSpecificDigest filtered to the user's teams with user-specific context."""
        filtered_digests = [team_digest for team_digest in self.team_digests if team_digest.id in user_teams]

        return UserSpecificDigest(
            id=self.id,
            name=self.name,
            created_at=self.created_at,
            team_digests=filtered_digests,
            context=context or UserDigestContext(),
        )

    def is_empty(self) -> bool:
        return all(digest.is_empty() for digest in self.team_digests)

    def count_items(self) -> int:
        return sum(td.count_items() for td in self.team_digests)


class UserSpecificDigest(BaseModel):
    """A user-specific view of an organization digest with user-specific fields."""

    id: UUID
    name: str
    created_at: datetime
    team_digests: list[TeamDigest]
    context: UserDigestContext = UserDigestContext()

    def is_empty(self) -> bool:
        return all(digest.is_empty() for digest in self.team_digests)

    def count_items(self) -> int:
        return sum(td.count_items() for td in self.team_digests)

    def render_payload(
        self, digest: Digest, event_definitions_limit: int | None = None
    ) -> dict[str, str | list | dict[str, str] | int | None]:
        teams = []
        product_suggestion = self.context.product_suggestion
        for td in self.team_digests:
            if td.is_empty():
                continue
            suggestion_for_team = (
                product_suggestion if product_suggestion and product_suggestion.team_id == td.id else None
            )
            teams.append(
                td.render_payload(
                    product_suggestion=suggestion_for_team, event_definitions_limit=event_definitions_limit
                )
            )

        return {
            "organization_name": self.name,
            "organization_id": str(self.id),
            "teams": teams,
            "scope": "user",
            "template_name": "weekly_digest_report",
            "period": digest.render_payload(),
            "digest_region": get_instance_region(),
        }


class PlaylistCount(BaseModel):
    session_ids: list[str] = []
    has_more: bool
    previous_ids: Optional[list[str]]
    refreshed_at: datetime
    error_count: int
    errored_at: Optional[datetime]
