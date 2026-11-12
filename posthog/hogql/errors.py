from abc import ABC
from typing import TYPE_CHECKING, ClassVar, Optional

if TYPE_CHECKING:
    from .ast import Expr

UNRESOLVED_FIELD_MESSAGE = "Unable to resolve field"
FIELD_NOT_FOUND_MESSAGE = "Field not found"

# Base


class BaseHogQLError(Exception, ABC):
    message: str
    start: Optional[int]
    end: Optional[int]
    fix: Optional[str]
    """Literal text the editor substitutes for the range between `start` and `end`, offered as a
    quick fix. Only set it when that range is known: the editor falls back to marking the whole
    query when a notice has no span, so a fix without one replaces everything the user typed."""

    def __init__(
        self,
        message: str,
        *,
        start: Optional[int] = None,
        end: Optional[int] = None,
        node: Optional["Expr"] = None,
        fix: Optional[str] = None,
    ):
        super().__init__(message)
        if node is not None and node.start is not None and node.end is not None:
            self.start = node.start
            self.end = node.end
        else:
            self.start = start
            self.end = end
        self.fix = fix


# Exposed vs. internal


class ExposedHogQLError(BaseHogQLError):
    """An exception that can be exposed to the user."""

    # Surfaced as the error code on API responses so clients can tell a deterministic query
    # failure from a transient blip without matching on the message. Subclasses override this
    # fallback with a more specific value.
    code_name = "hogql_error"


class InternalHogQLError(BaseHogQLError):
    """An internal exception in the HogQL engine."""

    pass


# Specific exceptions


class SyntaxError(ExposedHogQLError):
    """The input does not conform to HogQL syntax."""

    code_name = "hogql_syntax_error"


class QueryError(ExposedHogQLError):
    """The query is invalid, though correct syntactically."""

    code_name = "hogql_query_error"


class BoundedResolverError(QueryError):
    """Base class for saved view resolution failures: cycles, nesting depth and deadlines.

    Inherits from QueryError so callers that catch the public HogQL exception
    hierarchy (DRF handlers, workflow error mappers) keep treating these failures
    as user-facing 4xx errors rather than 500s. `initial_view` names the saved query
    whose resolution was in progress when the failure occurred, so callers can
    attribute and log the failure without having to plumb context through themselves.
    """

    status_label: ClassVar[str] = "error"

    def __init__(self, message: str, initial_view: str | None = None):
        super().__init__(message)
        self.initial_view = initial_view


class ResolutionCycleError(BoundedResolverError):
    """A view references itself through other views.

    `view_name` is the inner view at which the cycle was detected (the one
    already on the resolution stack). `initial_view` is the saved query the
    caller asked to resolve.
    """

    status_label: ClassVar[str] = "cycle"

    def __init__(self, view_name: str, initial_view: str | None = None):
        message = f"Circular dependency detected in view '{view_name}'"
        if initial_view and initial_view != view_name:
            message += f" while resolving '{initial_view}'"
        super().__init__(message, initial_view=initial_view)
        self.view_name = view_name


class ResolutionDepthExceededError(BoundedResolverError):
    """View resolution would exceed the configured nesting depth."""

    status_label: ClassVar[str] = "depth_exceeded"

    def __init__(self, depth: int, max_depth: int, initial_view: str | None = None):
        message = f"Query exceeds the limit of {max_depth} nested saved views. Reduce the view nesting depth."
        if initial_view:
            message += f" Resolving '{initial_view}'."
        super().__init__(message, initial_view=initial_view)
        self.depth = depth
        self.max_depth = max_depth


class TableAccessDeniedError(QueryError):
    """The user has no access to the table (raised by Database.get_table)."""

    # Surfaces as the error code on API responses (see posthog/api/query.py), so clients can tell a
    # denial from any other query error without matching on the message.
    code_name = "table_access_denied"

    table_name: str

    def __init__(self, table_name: str):
        super().__init__(f"You don't have access to table `{table_name}`.")
        self.table_name = table_name


class NotImplementedError(InternalHogQLError):
    """This feature isn't implemented in HogQL (yet)."""

    pass


class ParsingError(InternalHogQLError):
    """Parsing failed."""

    pass


class ImpossibleASTError(InternalHogQLError):
    """Parsing or resolution resulted in an impossible AST."""

    pass


class ResolutionError(InternalHogQLError):
    """Resolution of a table/field/expression failed."""

    pass
