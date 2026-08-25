"""Which check subjects the caller may not read.

The REST endpoint and the ``information_schema.data_quality_*`` tables must never disagree on
visibility, so both resolve denial from the same source: the warehouse-table denial the HogQL
database computes for the caller. A member denied a table or view must not read its checks, run
history, or health rollup -- those carry the compiled ``config``, failed-row counts, and observed
values, which together act as a count oracle over rows the member cannot read directly.
"""

from typing import TYPE_CHECKING, Any, Optional

from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.information_schema import _references_denied_table

from .registry import all_specs, get_spec
from .spec import CheckTypeSpec
from .subjects import resolve_subject

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.access_control.backend.facade.user_access_control import UserAccessControl


def denied_subject_names(
    team: "Team", user: "User", user_access_control: Optional["UserAccessControl"] = None
) -> set[str]:
    """The warehouse table/view identifiers this caller cannot query, as the HogQL database sees them.

    This is the exact set the ``information_schema`` loaders consult, so the two paths stay in
    lock-step. Fails closed with no principal (the database denies every warehouse table)."""
    database = Database.create_for(team=team, user=user, user_access_control=user_access_control)
    return set(database._denied_tables)


def is_subject_denied(subject_name: str, denied: set[str]) -> bool:
    """Whether a check's subject is in the caller's denied set, matched the same way the loaders match."""
    return _references_denied_table([subject_name], denied)


# A check type reads beyond its declared subject only if it overrides one of these hooks: a
# ``relationships`` check names a target subject, a ``custom_sql`` query selects arbitrary tables.
# Derived from the specs rather than hard-coded so a new referencing type can't silently slip the net.
_REFERENCING_CHECK_TYPES: frozenset[str] = frozenset(
    str(spec.type_name)
    for spec in all_specs()
    if type(spec).related_subject_ref is not CheckTypeSpec.related_subject_ref
    or type(spec).referenced_table_names is not CheckTypeSpec.referenced_table_names
)


def check_type_reads_beyond_subject(check_type: str) -> bool:
    """Whether this check type can read warehouse objects other than its declared subject.

    Used to fail closed when a run's definition was hard-deleted: without the config we can no longer
    enumerate the referenced subjects, so a ``relationships`` or ``custom_sql`` run must be treated as
    if it could touch a denied one."""
    return check_type in _REFERENCING_CHECK_TYPES


def referencing_check_types() -> frozenset[str]:
    """The check types that read beyond their declared subject (``relationships``, ``custom_sql``).

    A cheap pre-filter so a denied-reference scan only parses the config of checks that can carry one,
    rather than every check on the team."""
    return _REFERENCING_CHECK_TYPES


def check_reads_denied_subject(team_id: int, check_type: str, config: dict[str, Any], denied: set[str]) -> bool:
    """Whether a check reads any subject *besides its declared one* that the caller is denied.

    The single test the health rollup and suite-summary guards share, so the REST endpoint and the
    ``information_schema`` tables stay in lock-step about which referencing checks a member may see."""
    if not denied:
        return False
    return any(is_subject_denied(name, denied) for name in referenced_subject_names(team_id, check_type, config))


def referenced_subject_names(team_id: int, check_type: str, config: dict[str, Any]) -> list[str]:
    """Every warehouse name a check reads *besides* its declared subject.

    A ``relationships`` check names a second subject and a ``custom_sql`` query selects from arbitrary
    tables; the worker later runs both with team scope only. Authorizing these at the API is the one
    place a denied subject can be kept out of reach, so a check on an allowed subject can't be used as
    a count oracle over one the author cannot read. Assumes config already validated."""
    spec = get_spec(check_type)
    parsed = spec.parse_config(config)
    names = list(spec.referenced_table_names(parsed))
    if related := spec.related_subject_ref(parsed):
        ref = resolve_subject(team_id, related[0], related[1])
        if ref.exists:
            names.append(ref.name)
    return names
