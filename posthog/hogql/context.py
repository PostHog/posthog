from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Optional

from posthog.hogql.timings import HogQLTimings
from posthog.schema import HogQLNotice, HogQLQueryModifiers
from posthog.hogql.constants import LimitContext

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database
    from posthog.hogql.transforms.property_types import PropertySwapper
    from posthog.models import Team


@dataclass
class HogQLFieldAccess:
    input: list[str]
    type: Optional[Literal["event", "event.properties", "person", "person.properties"]]
    field: Optional[str]
    sql: str


@dataclass
class HogQLContext:
    """Context given to a HogQL expression printer"""

    # Team making the queries
    team_id: Optional[int] = None
    # Team making the queries - if team is passed in, then the team isn't queried when creating the database
    team: Optional["Team"] = None
    # Virtual database we're querying, will be populated from team_id if not present
    database: Optional["Database"] = None
    # If set, will save string constants to this dict. Inlines strings into the query if None.
    values: dict = field(default_factory=dict)
    # Are we small part of a non-HogQL query? If so, use custom syntax for accessed person properties.
    within_non_hogql_query: bool = False
    # Enable full SELECT queries and subqueries in ClickHouse
    enable_select_queries: bool = False
    # Do we apply a limit of MAX_SELECT_RETURNED_ROWS=10000 to the topmost select query?
    limit_top_select: bool = True
    # Context for determining the appropriate limit to apply
    limit_context: Optional[LimitContext] = None
    # Apply a FORMAT clause to output data in given format.
    output_format: str | None = None
    # Globals that will be resolved in the context of the query
    globals: Optional[dict] = None

    # Warnings returned with the metadata query
    warnings: list["HogQLNotice"] = field(default_factory=list)
    # Notices returned with the metadata query
    notices: list["HogQLNotice"] = field(default_factory=list)
    # Errors returned with the metadata query
    errors: list["HogQLNotice"] = field(default_factory=list)

    # Timings in seconds for different parts of the HogQL query
    timings: HogQLTimings = field(default_factory=HogQLTimings)
    # Modifications requested by the HogQL client
    modifiers: HogQLQueryModifiers = field(default_factory=HogQLQueryModifiers)
    # Enables more verbose output for debugging
    debug: bool = False

    property_swapper: Optional["PropertySwapper"] = None

    def __post_init__(self):
        if self.team:
            self.team_id = self.team.id

    def add_value(self, value: Any) -> str:
        key = f"hogql_val_{len(self.values)}"
        self.values[key] = value
        return f"%({key})s"

    def add_sensitive_value(self, value: Any) -> str:
        key = f"hogql_val_{len(self.values)}_sensitive"
        self.values[key] = value
        return f"%({key})s"

    def add_notice(
        self,
        message: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        fix: Optional[str] = None,
    ):
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.notices):
            self.notices.append(HogQLNotice(start=start, end=end, message=message, fix=fix))

    def add_warning(
        self,
        message: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        fix: Optional[str] = None,
    ):
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.warnings):
            self.warnings.append(HogQLNotice(start=start, end=end, message=message, fix=fix))

    def add_error(
        self,
        message: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        fix: Optional[str] = None,
    ):
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.errors):
            self.errors.append(HogQLNotice(start=start, end=end, message=message, fix=fix))

    @cached_property
    def project_id(self) -> int:
        from posthog.models import Team

        if not self.team and not self.team_id:
            raise ValueError("Either team or team_id must be set to determine project_id")
        team = self.team or Team.objects.only("project_id").get(id=self.team_id)
        return team.project_id
