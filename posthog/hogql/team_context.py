from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from posthog.models import Team


@dataclass(frozen=True, slots=True)
class HogQLTeamContext:
    """The team configuration the HogQL engine reads, captured as plain data.

    This is the framework-free contract that stands in for passing a Django ``Team``
    into the engine. Build it at the Django boundary with ``from_team`` (or by hand in
    tests); engine code then depends only on this immutable data, never on the ORM.

    Only cheap, directly-readable team attributes belong here. Values that need a
    feature-flag evaluation or a database read — the persons-on-events default,
    materialized columns, cohort definitions — are deliberately excluded; they reach the
    engine as already-resolved data through the data provider, so building this context
    never triggers I/O.
    """

    # Identity / tenant scoping
    team_id: int
    project_id: int
    uuid: str
    organization_id: str

    # Query semantics (all cheap stored fields)
    timezone: str
    week_start_day: Optional[int] = None
    base_currency: Optional[str] = None
    # Raw ``team.modifiers`` JSON — project-level HogQL modifier overrides applied during
    # default-modifier resolution.
    modifiers: Optional[dict] = None
    # Raw ``team.test_account_filters`` JSON (list of property-filter dicts).
    test_account_filters: list[Any] = field(default_factory=list)
    # Raw ``team.path_cleaning_filters`` JSON (list of regex/alias dicts).
    path_cleaning_filters: list[Any] = field(default_factory=list)

    @property
    def timezone_info(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @classmethod
    def from_team(cls, team: "Team") -> "HogQLTeamContext":
        """Build the context from a Django ``Team`` — the one place the ORM is read.

        Reads attributes off the instance; performs no feature-flag evaluation and no
        database query of its own.
        """
        return cls(
            team_id=team.id,
            project_id=team.project_id,
            uuid=str(team.uuid),
            organization_id=str(team.organization_id),
            timezone=team.timezone,
            week_start_day=team.week_start_day,
            base_currency=team.base_currency,
            modifiers=team.modifiers,
            test_account_filters=team.test_account_filters or [],
            path_cleaning_filters=team.path_cleaning_filters or [],
        )
