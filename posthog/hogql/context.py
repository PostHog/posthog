from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


@dataclass
class HogQLFieldAccess:
    input: List[str]
    type: Optional[Literal["event", "event.properties", "person", "person.properties"]]
    field: Optional[str]
    sql: str


@dataclass
class HogQLContext:
    """Context given to a HogQL expression printer"""

    # If set, will save string constants to this dict. Inlines strings into the query if None.
    values: Dict = field(default_factory=dict)
    # List of field and property accesses found in the expression
    field_access_logs: List[HogQLFieldAccess] = field(default_factory=list)
    # Did the last calls to translate_hogql since setting these to False contain any of the following
    found_aggregation: bool = False
    # Do we need to join the persons table or not
    using_person_on_events: bool = True
    # If set, allows printing full SELECT queries in ClickHouse
    select_team_id: Optional[int] = None
    # Do we apply a limit of MAX_SELECT_RETURNED_ROWS=65535 to the topmost select query?
    limit_top_select: bool = True
