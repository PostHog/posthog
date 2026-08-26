"""Which check subjects the caller may not read.

The REST endpoint and the ``information_schema.data_quality_*`` tables must never disagree on
visibility, so both resolve denial from the same source: the warehouse-table denial the HogQL
database computes for the caller. A member denied a table or view must not read its checks, run
history, or health rollup -- those carry the compiled ``config``, failed-row counts, and observed
values, which together act as a count oracle over rows the member cannot read directly.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from django.db.models import Q

from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.information_schema import _references_denied_table

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from ..facade.enums import SubjectType
from ..models import DataQualityCheckRunSubject
from .contracts import SubjectIdentity
from .registry import all_specs, get_spec
from .spec import CheckTypeSpec
from .subjects import resolve_subject, resolve_subject_by_name, resolve_subject_names

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


def can_be_object_denied(user_access_control: Optional["UserAccessControl"]) -> bool:
    """Whether object-level warehouse denial can apply to this caller at all.

    False for an org admin, or an organization without access controls: neither can be denied a
    single table or view, so an empty denial set is proof of access rather than missing data. For
    everyone else the set can also be empty *because* the subject they were denied was deleted, so
    this -- never the emptiness of the set -- decides whether a gate applies.
    """
    return (
        user_access_control is not None
        and not user_access_control.is_organization_admin
        and user_access_control.access_controls_supported
    )


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


@frozen
class ReferencedSubjects:
    """What a check reads besides its declared subject, and whether that could be established.

    ``unresolved_reference`` is the part a name list cannot carry: a ``relationships`` target that no
    longer resolves leaves no name behind, so a caller matching names alone would read "references
    nothing" from a subject that was deleted out from under the denial set."""

    names: tuple[str, ...]
    unresolved_reference: bool


def referenced_subjects(team_id: int, check_type: str, config: dict[str, Any]) -> ReferencedSubjects:
    """Every warehouse name a check reads *besides* its declared subject.

    A ``relationships`` check names a second subject and a ``custom_sql`` query selects from arbitrary
    tables; the worker later runs both with team scope only. Authorizing these at the API is the one
    place a denied subject can be kept out of reach, so a check on an allowed subject can't be used as
    a count oracle over one the author cannot read. Assumes config already validated."""
    spec = get_spec(check_type)
    parsed = spec.parse_config(config)
    names = list(spec.referenced_table_names(parsed))
    unresolved = False
    if related := spec.related_subject_ref(parsed):
        ref = resolve_subject(team_id, related[0], related[1])
        if ref.exists:
            names.append(ref.name)
        else:
            unresolved = True
    return ReferencedSubjects(names=tuple(names), unresolved_reference=unresolved)


def referenced_subject_names(team_id: int, check_type: str, config: dict[str, Any]) -> list[str]:
    """The names from :func:`referenced_subjects`, for callers that only report or match on them."""
    return list(referenced_subjects(team_id, check_type, config).names)


_SUBJECT_TYPE_KEY = "subject_type"
_SUBJECT_UUID_KEY = "subject_uuid"


def pin_referenced_subjects(team_id: int, check_type: str, config: dict[str, Any]) -> list[dict[str, str]] | None:
    """The identities of the subjects this run reads besides its own, to record alongside the run.

    Names cannot carry this. Deleting a warehouse object frees its name, so a recorded name starts
    naming whatever a member creates in its place, and history read back by name hands them what the
    run read over an object they were denied. An identity survives that: the reused name resolves to
    a different id, and the recorded id stops resolving.

    ``None`` when the references cannot be established at all, so a reader falls back to judging the
    run by its type rather than reading an empty list as "read nothing".
    """
    try:
        spec = get_spec(check_type)
        parsed = spec.parse_config(config)
        pinned = [
            subject for name in spec.referenced_table_names(parsed) if (subject := _pin_name(team_id, name)) is not None
        ]
        if related := spec.related_subject_ref(parsed):
            pinned.append(SubjectIdentity(subject_type=str(related[0]), subject_uuid=str(related[1])))
    except Exception as err:
        capture_exception(err)
        return None
    return [{_SUBJECT_TYPE_KEY: subject.subject_type, _SUBJECT_UUID_KEY: subject.subject_uuid} for subject in pinned]


def pinned_subjects(recorded: Any) -> list[SubjectIdentity] | None:
    """The identities a run recorded, or None when it recorded nothing judgeable.

    A malformed entry reads as nothing recorded rather than as an empty list, so a run whose
    recording cannot be trusted falls back to the same type-based rule as one predating it. An
    entry is only judgeable if it can be resolved, so the type and the id are validated here rather
    than left to raise on whichever surface reads the column."""
    if not isinstance(recorded, list):
        return None
    subjects: list[SubjectIdentity] = []
    for entry in recorded:
        if not isinstance(entry, dict):
            return None
        subject_type, subject_uuid = entry.get(_SUBJECT_TYPE_KEY), entry.get(_SUBJECT_UUID_KEY)
        if not isinstance(subject_type, str) or not isinstance(subject_uuid, str):
            return None
        if not _is_resolvable(subject_type, subject_uuid):
            return None
        subjects.append(SubjectIdentity(subject_type=subject_type, subject_uuid=subject_uuid))
    return subjects


def pinned_subject_refs(recordings: Iterable[Any]) -> list[SubjectIdentity]:
    """Every identity across these recordings, for one bulk name resolution over a page of runs."""
    return [subject for recorded in recordings for subject in pinned_subjects(recorded) or []]


def run_reads_unreadable_subject(
    check_type: str, recorded: Any, current_names: Mapping[SubjectIdentity, str], denied: set[str]
) -> bool:
    """Whether a recorded run read a subject the caller cannot be shown to be allowed.

    The one test every surface serving run history applies, so the REST routes and the
    ``information_schema`` loaders cannot come to different answers about the same run. Judged from
    the identities the run pinned as it executed: never from the definition its check carries now,
    which an edit rewrites, and never from names, which deleting an object frees for anyone to take.

    A subject missing from ``current_names`` no longer resolves, and took its denial with it, so
    nothing left can show the caller was allowed it. A run that pinned nothing predates the
    recording and is judged by its type instead: one that cannot read past its own subject read only
    the subject this surface already authorized, and anything that can is withheld.
    """
    pinned = pinned_subjects(recorded)
    if pinned is None:
        return check_type_reads_beyond_subject(check_type)
    return any((name := current_names.get(subject)) is None or is_subject_denied(name, denied) for subject in pinned)


def unreadable_runs_q(team_id: int, denied: set[str]) -> Q:
    """Match, in SQL, every run that read a subject this caller cannot be shown to be allowed.

    The set form of :func:`run_reads_unreadable_subject`, for the surfaces that have to exclude
    before a window or a page count and so cannot judge run by run in Python. Three ways a run is
    out of reach, and none of them aggregates over the recorded JSON:

    - it read a subject that no longer resolves, or resolves to a name the caller is denied, which
      the index answers by id;
    - it pinned nothing and its type can read past its own subject, so what it read cannot be
      established;
    - it recorded references but has no index rows for them, which is the same "cannot be
      established" in a different form and is treated the same way.

    The last case is what makes the index safe to add without rewriting history: a run written
    before it existed is withheld rather than read as one that referenced nothing.
    """
    indexed = DataQualityCheckRunSubject.objects.for_team(team_id)
    matched = Q(referenced_subjects__isnull=True, check_type__in=referencing_check_types())
    matched |= ~Q(referenced_subjects__isnull=True) & ~Q(referenced_subjects=[]) & ~Q(id__in=indexed.values("run_id"))
    if blocked := _blocked_subjects(team_id, denied):
        matched |= Q(id__in=indexed.filter(blocked).values("run_id"))
    return matched


def _blocked_subjects(team_id: int, denied: set[str]) -> Q:
    """The indexed subjects this caller may not read, as a filter over the index. One query to list.

    Distinct over two narrow indexed columns, so the cost tracks how many subjects the project has
    rather than how long its run history is.
    """
    referenced = [
        SubjectIdentity(subject_type=subject_type, subject_uuid=str(subject_uuid))
        for subject_type, subject_uuid in DataQualityCheckRunSubject.objects.for_team(team_id)
        .values_list("subject_type", "subject_uuid")
        .distinct()
    ]
    current_names = resolve_subject_names(team_id, referenced)
    by_type: dict[str, list[UUID]] = defaultdict(list)
    for subject in referenced:
        name = current_names.get(subject)
        if name is None or is_subject_denied(name, denied):
            by_type[subject.subject_type].append(UUID(subject.subject_uuid))
    blocked = Q()
    for subject_type, uuids in by_type.items():
        blocked |= Q(subject_type=subject_type, subject_uuid__in=uuids)
    return blocked


def _is_resolvable(subject_type: str, subject_uuid: str) -> bool:
    try:
        SubjectType(subject_type)
        UUID(subject_uuid)
    except ValueError:
        return False
    return True


def _pin_name(team_id: int, name: str) -> SubjectIdentity | None:
    ref = resolve_subject_by_name(team_id, name)
    if ref is None:
        return None
    return SubjectIdentity(subject_type=str(ref.subject_type), subject_uuid=ref.subject_uuid)


def unconfirmable_subject_names(
    team: "Team",
    user: "User",
    names: tuple[str, ...],
    user_access_control: Optional["UserAccessControl"] = None,
) -> set[str]:
    """The referenced names this caller can neither resolve nor be shown to have been denied.

    Deleting a warehouse object takes its denial with it: the name leaves the database the caller
    can resolve *and* the denial set that is rebuilt from the objects that still exist, so a run
    that once read a denied table starts reading as harmless. Neither state proves access, so both
    are reported and the caller fails them closed -- the same stance ``_require_parent_subject_access``
    already takes for the subject a check hangs off."""
    if not names:
        return set()
    database = Database.create_for(team=team, user=user, user_access_control=user_access_control)
    return {name for name in names if not database.has_table(name) and not database.is_table_access_denied(name)}
