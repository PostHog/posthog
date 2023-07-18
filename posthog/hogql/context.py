from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Any

from posthog.hogql.database.database import Database
from posthog.schema import HogQLNotice
from posthog.utils import PersonOnEventsMode


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
    database: Optional[Database] = None
    # If set, will save string constants to this dict. Inlines strings into the query if None.
    values: Dict = field(default_factory=dict)
    # Are we small part of a non-HogQL query? If so, use custom syntax for accessed person properties.
    within_non_hogql_query: bool = False
    # Do we need to join the persons table or not. Has effect if within_non_hogql_query = True
    person_on_events_mode: PersonOnEventsMode = PersonOnEventsMode.V1_ENABLED
    # Enable full SELECT queries and subqueries in ClickHouse
    enable_select_queries: bool = False
    # Do we apply a limit of MAX_SELECT_RETURNED_ROWS=10000 to the topmost select query?
    limit_top_select: bool = True

    # Warnings returned with the metadata query
    warnings: List[HogQLNotice] = field(default_factory=list)
    # Notices returned with the metadata query
    notices: List[HogQLNotice] = field(default_factory=list)

    def add_value(self, value: Any) -> str:
        key = f"hogql_val_{len(self.values)}"
        self.values[key] = value
        return f"%({key})s"

    def add_sensitive_value(self, value: Any) -> str:
        key = f"hogql_val_{len(self.values)}_sensitive"
        self.values[key] = value
        return f"%({key})s"
