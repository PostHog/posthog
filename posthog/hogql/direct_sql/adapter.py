import dataclasses
from dataclasses import field
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from posthog.hogql.constants import HogQLDialect, HogQLGlobalSettings
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource

from posthog.dataclasses import frozen

_ConfigT_co = TypeVar("_ConfigT_co", covariant=True)


class _ParseableSource(Protocol[_ConfigT_co]):
    def parse_config(self, job_inputs: dict) -> _ConfigT_co: ...


def parse_direct_source_config(source_impl: _ParseableSource[_ConfigT_co], source: "ExternalDataSource") -> _ConfigT_co:
    """Build a source's connection config from its stored ``job_inputs``.

    A direct-capable source can reach a live query with empty or incomplete ``job_inputs``
    (credentials never finished setup, were cleared, or can't be decrypted). Config building then
    raises a raw ``TypeError``/``ValueError`` that would otherwise leak to error tracking; convert
    it to a clean user-facing error instead.
    """
    try:
        return source_impl.parse_config(source.job_inputs or {})
    except (TypeError, ValueError) as error:
        raise ExposedHogQLError("This source is missing its connection configuration.") from error


@frozen
class DirectQueryPrincipal:
    value: str


@dataclasses.dataclass(frozen=False)
class DirectQueryRequest:
    source: "ExternalDataSource"
    team: "Team"
    sql: str
    values: dict[str, object] | None
    settings: HogQLGlobalSettings
    timings: HogQLTimings
    query_type: str
    debug: bool
    principal: DirectQueryPrincipal | None = field(default=None)
    cancellation_token: str | None = None


@dataclasses.dataclass(frozen=False)
class DirectQueryResult:
    results: list
    types: list[tuple[str, str]]
    print_columns: list[str]
    error: str | None = None


class DirectSQLAdapter(Protocol):
    """Contract every direct-query engine implements. The registry keys adapters by ``engine``.

    ``dialect`` is the HogQL printer dialect the engine compiles to, or ``None`` for raw-only
    engines (no printer — only ``sendRawQuery`` works). Phase 1 engines (Postgres, MySQL) both
    have a dialect; raw-only engines arrive in Phase 2.
    """

    engine: str
    dialect: HogQLDialect | None

    def validate_source_config(self, source: "ExternalDataSource", team: "Team") -> tuple[Any, Any]:
        """Validate the source is queryable (host/SSRF + SSH tunnel) and return (implementation, config)."""
        ...

    def prepare_raw_sql(self, sql: str) -> str:
        """Apply the engine's raw-statement guards to user-supplied SQL."""
        ...

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        """Connect, apply engine execution controls, run the SQL, and map results/types back."""
        ...
