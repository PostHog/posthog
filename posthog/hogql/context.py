from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Literal, Optional, Any

from posthog.hogql.timings import HogQLTimings
from posthog.schema import HogQLNotice, HogQLQueryModifiers

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database


@dataclass
class HogQLFieldAccess:
    input: List[str]
    type: Optional[Literal["event", "event.properties", "person", "person.properties"]]
    field: Optional[str]
    sql: str


@dataclass
class HogQLContext:
    """Context given to a HogQL expression printer"""

    # Team making the queries
    team_id: Optional[int]
    # Virtual database we're querying, will be populated from team_id if not present
    database: Optional["Database"] = None
    # If set, will save string constants to this dict. Inlines strings into the query if None.
    values: Dict = field(default_factory=dict)
    # Are we small part of a non-HogQL query? If so, use custom syntax for accessed person properties.
    within_non_hogql_query: bool = False
    # Enable full SELECT queries and subqueries in ClickHouse
    enable_select_queries: bool = False
    # Do we apply a limit of MAX_SELECT_RETURNED_ROWS=10000 to the topmost select query?
    limit_top_select: bool = True
    # How many nested views do we support on this query?
    max_view_depth: int = 1

    # Warnings returned with the metadata query
    warnings: List["HogQLNotice"] = field(default_factory=list)
    # Notices returned with the metadata query
    notices: List["HogQLNotice"] = field(default_factory=list)
    # Timings in seconds for different parts of the HogQL query
    timings: HogQLTimings = field(default_factory=HogQLTimings)
    # Modifications requested by the HogQL client
    modifiers: HogQLQueryModifiers = field(default_factory=HogQLQueryModifiers)

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
