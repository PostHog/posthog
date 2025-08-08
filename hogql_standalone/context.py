"""
Standalone HogQL context without Django dependencies.
This replaces the Django-dependent HogQLContext.
"""
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal, Optional

from .data_types import HogQLDataBundle, HogQLDataProvider

if TYPE_CHECKING:
    pass  # Import types only when needed for type checking


@dataclass
class HogQLNotice:
    """Notice/warning/error message"""
    message: str
    start: Optional[int] = None
    end: Optional[int] = None
    fix: Optional[str] = None


@dataclass
class HogQLQueryModifiers:
    """Query modification options"""
    # Add common modifiers that don't depend on Django
    pass


@dataclass
class HogQLTimings:
    """Timing information for query execution"""
    
    def __init__(self):
        self._timings: dict[str, float] = {}
    
    def record(self, name: str, duration: float):
        self._timings[name] = duration
    
    def get(self, name: str) -> Optional[float]:
        return self._timings.get(name)
    
    def all(self) -> dict[str, float]:
        return self._timings.copy()


class LimitContext:
    """Context for determining query limits"""
    pass  # Simplified version


@dataclass
class HogQLFieldAccess:
    """Information about field access in a query"""
    input: list[str]
    type: Optional[Literal["event", "event.properties", "person", "person.properties"]]
    field: Optional[str]
    sql: str


@dataclass
class StandaloneHogQLContext:
    """
    Standalone HogQL context that doesn't depend on Django models.
    All data is injected via the data_provider.
    """
    
    # Data provider that supplies all external data
    data_provider: HogQLDataProvider
    
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
    warnings: list[HogQLNotice] = field(default_factory=list)
    
    # Notices returned with the metadata query
    notices: list[HogQLNotice] = field(default_factory=list)
    
    # Errors returned with the metadata query
    errors: list[HogQLNotice] = field(default_factory=list)
    
    # Timings in seconds for different parts of the HogQL query
    timings: HogQLTimings = field(default_factory=HogQLTimings)
    
    # Modifications requested by the HogQL client
    modifiers: HogQLQueryModifiers = field(default_factory=HogQLQueryModifiers)
    
    # Enables more verbose output for debugging
    debug: bool = False
    
    # Cache for the data bundle to avoid repeated calls
    _data_bundle: Optional[HogQLDataBundle] = field(default=None, init=False)
    
    @cached_property
    def data_bundle(self) -> HogQLDataBundle:
        """Get the data bundle, caching it after first access"""
        if self._data_bundle is None:
            self._data_bundle = self.data_provider.get_data_bundle()
        return self._data_bundle
    
    @cached_property
    def team_id(self) -> int:
        """Get team ID from the injected data"""
        return self.data_bundle.team.id
    
    @cached_property
    def project_id(self) -> int:
        """Get project ID from the injected data"""
        if self.data_bundle.team.project_id is not None:
            return self.data_bundle.team.project_id
        # Fallback: assume team_id == project_id if project_id not set
        return self.data_bundle.team.id
    
    def add_value(self, value: Any) -> str:
        """Add a parameterized value to the query"""
        key = f"hogql_val_{len(self.values)}"
        self.values[key] = value
        return f"%({key})s"
    
    def add_sensitive_value(self, value: Any) -> str:
        """Add a sensitive parameterized value to the query"""
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
        """Add a notice to the context"""
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.notices):
            self.notices.append(HogQLNotice(start=start, end=end, message=message, fix=fix))
    
    def add_warning(
        self,
        message: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        fix: Optional[str] = None,
    ):
        """Add a warning to the context"""
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.warnings):
            self.warnings.append(HogQLNotice(start=start, end=end, message=message, fix=fix))
    
    def add_error(
        self,
        message: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        fix: Optional[str] = None,
    ):
        """Add an error to the context"""
        if not any(n.start == start and n.end == end and n.message == message and n.fix == fix for n in self.errors):
            self.errors.append(HogQLNotice(start=start, end=end, message=message, fix=fix))


# For backwards compatibility during migration
HogQLContext = StandaloneHogQLContext