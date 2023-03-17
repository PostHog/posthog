from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from posthog.hogql.database import Database


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
    using_person_on_events: bool = True
    # Enable full SELECT queries and subqueries in ClickHouse
    enable_select_queries: bool = False
    # Do we apply a limit of MAX_SELECT_RETURNED_ROWS=65535 to the topmost select query?
    limit_top_select: bool = True
