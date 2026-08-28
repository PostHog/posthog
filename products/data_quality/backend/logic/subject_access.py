"""Which check subjects the caller may read, and what that hides.

The REST endpoint and the ``information_schema.data_quality_*`` tables must never disagree on
visibility, so both resolve denial from the same source: the warehouse-table denial the HogQL
database computes for the caller. A member denied a table or view must not read its checks, run
history, or health rollup -- those carry the compiled ``config``, failed-row counts, and observed
values, which together act as a count oracle over rows the member cannot read directly.

Every verdict here is the negation of an explicit readable predicate, over a snapshot of the
subjects the caller may read. A subject that is denied, deleted, or of a kind this gate does not
know is absent from that snapshot and therefore out of reach.
"""

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from django.db.models import Exists, OuterRef, Q

from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.information_schema import _references_denied_table

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade import api as data_modeling_facade
from products.warehouse_sources.backend.facade import api as warehouse_facade

from ..facade.enums import SubjectType
from ..models import DataQualityCheck, DataQualityCheckRun
from .checks import latest_run_ids
from .contracts import SubjectIdentity
from .registry import all_specs, get_spec
from .spec import CheckTypeSpec
from .subjects import resolve_subject, resolve_subject_by_name

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

_SUBJECT_TYPE_KEY = "subject_type"
_SUBJECT_UUID_KEY = "subject_uuid"


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


@frozen
class ReadableSubjects:
    """The warehouse subjects this caller may read, by id.

    A snapshot of what exists *and* is allowed right now. Absence is the single verdict every gate
    negates: a denied subject is absent because its name matched the denial set, a deleted one
    because it no longer exists, and a subject of a kind this gate does not know because neither
    branch below claims it.
    """

    table_ids: frozenset[UUID]
    view_ids: frozenset[UUID]

    def contains(self, subject_type: str, subject_uuid: str | UUID | None) -> bool:
        if subject_uuid is None:
            return False
        try:
            identifier = UUID(str(subject_uuid))
        except ValueError:
            return False
        if subject_type == SubjectType.TABLE:
            return identifier in self.table_ids
        if subject_type == SubjectType.VIEW:
            return identifier in self.view_ids
        return False


@frozen
class DenialContext:
    """Everything a gate needs about one caller, resolved once and passed down.

    ``readable`` answers the identity-keyed questions a stored row asks, ``denied`` the name-keyed
    ones a definition asks, and ``database`` is the caller's own HogQL database -- carried so a
    surface that has already built one never builds a second.
    """

    readable: ReadableSubjects
    denied: set[str]
    database: Database


def readable_subjects(team_id: int, denied: set[str]) -> ReadableSubjects:
    """The team's live warehouse subjects, minus the ones this caller is denied. Two queries.

    Cost tracks the objects the team has, not the length of retained history, which is what makes
    it safe to hold a whole page of run history up against.
    """
    tables = warehouse_facade.all_queryable_table_names(team_id)
    views = data_modeling_facade.all_saved_query_names(team_id)
    return ReadableSubjects(
        table_ids=frozenset(table_id for table_id, name in tables.items() if not is_subject_denied(name, denied)),
        view_ids=frozenset(UUID(view_id) for view_id, name in views.items() if not is_subject_denied(name, denied)),
    )


def denial_context(team_id: int, database: Database) -> DenialContext:
    """The caller's denial state, from a HogQL database that has already been built for them."""
    denied = set(database._denied_tables)
    return DenialContext(readable=readable_subjects(team_id, denied), denied=denied, database=database)


def caller_denial_context(
    team: "Team", user: "User", user_access_control: Optional["UserAccessControl"] = None
) -> DenialContext:
    """The caller's denial state, building the HogQL database this request will reuse."""
    return denial_context(team.id, Database.create_for(team=team, user=user, user_access_control=user_access_control))


def unreadable_runs_q(context: DenialContext) -> Q:
    """Match, in SQL, every run that touched a subject this caller may not read.

    Judged from the run's own columns, so the answer holds for a run whose definition was edited or
    hard-deleted, and a surface can exclude before a window or a page count. Three ways out of reach:

    - the subject the run declared is not readable, which covers denied and deleted alike;
    - it recorded no references and its type can read past its own subject, so what it read cannot
      be established at all;
    - it recorded references that are not all readable.
    """
    unreadable_declared = ~_readable_subject_q(context.readable)
    unknowable_references = Q(referenced_subjects__isnull=True, check_type__in=referencing_check_types())
    unreadable_references = ~Q(referenced_subjects__isnull=True) & ~Q(
        referenced_subjects__contained_by=_readable_identities(context.readable)
    )
    return unreadable_declared | unknowable_references | unreadable_references


def unreadable_suites_q(context: DenialContext) -> Q:
    """Match, in SQL, every suite whose own subject this caller may not read.

    Only a suite that targets exactly one subject records one. A sweep across several records none,
    so it is judged by the runs it covers instead and must not be matched here.
    """
    return Q(subject_uuid__isnull=False) & ~_readable_subject_q(context.readable)


def suites_backing_unreadable_runs_q(team_id: int, context: DenialContext) -> Q:
    """Match, in SQL, every suite that covers a run this caller may not read.

    A suite row carries passed/failed/errored/skipped over every check it ran, while its run list
    hands back only the readable ones, so serving both names the withheld run's outcome by
    subtraction. Correlated per suite rather than collected across the project first, so a page costs
    an index probe per suite it examines instead of a pass over retained history.
    """
    covered = DataQualityCheckRun.objects.for_team(team_id).filter(
        unreadable_runs_q(context), suite_run_id=OuterRef("pk")
    )
    return Q(Exists(covered))


def hidden_check_ids(team_id: int, checks: Sequence[DataQualityCheck], context: DenialContext) -> set[UUID]:
    """The ids of the checks this caller may not see, over a page of them.

    A check is out of reach on any of three counts: its own subject is unreadable, the definition it
    would run next reads one that is, or the run behind its ``last_status`` read one. The row is both
    tenses at once, so each is judged by the rule for its own tense -- the definition by the names it
    resolves today, the stored run by the identities it recorded.
    """
    hidden = {check.id for check in checks if not context.readable.contains(check.subject_type, check.subject_uuid)}
    verdicts: dict[str, bool] = {}
    for check in checks:
        if check.id in hidden:
            continue
        if _memoized_definition_verdict(team_id, check.check_type, check.config or {}, context, verdicts):
            hidden.add(check.id)
    return hidden | _checks_whose_latest_run_is_unreadable(
        team_id, [check.id for check in checks if check.id not in hidden], context
    )


def definition_reads_unreadable_subject(
    team_id: int, check_type: str, config: dict[str, Any], context: DenialContext
) -> bool:
    """Whether the definition a check would run next reads a subject beyond a caller's reach.

    The parent is not the only subject a check reads: a ``relationships`` check names a second
    subject and a ``custom_sql`` query selects arbitrary tables, both run by the worker with team
    scope only. Matched by name, because a definition names its references rather than pinning them:
    a name that is denied, that no longer resolves, or that resolves to neither an allowed nor a
    denied object proves nothing in the caller's favor.
    """
    if not check_type_reads_beyond_subject(check_type):
        return False
    refs = referenced_subjects(team_id, check_type, config)
    if refs.unresolved_reference:
        return True
    if any(is_subject_denied(name, context.denied) for name in refs.names):
        return True
    return bool(unconfirmable_subject_names(refs.names, context.database))


def unconfirmable_subject_names(names: tuple[str, ...], database: Database) -> set[str]:
    """The referenced names this caller can neither resolve nor be shown to have been denied.

    Deleting a warehouse object takes its denial with it: the name leaves the database the caller
    can resolve *and* the denial set that is rebuilt from the objects that still exist, so a check
    that once read a denied table starts reading as harmless. Neither state proves access, so both
    are reported and the caller fails them closed."""
    return {name for name in names if not database.has_table(name) and not database.is_table_access_denied(name)}


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

    Used to fail closed when a run recorded no references: without them we cannot enumerate what a
    ``relationships`` or ``custom_sql`` run touched, so it is treated as if it could have touched
    anything."""
    return check_type in _REFERENCING_CHECK_TYPES


def referencing_check_types() -> frozenset[str]:
    """The check types that read beyond their declared subject (``relationships``, ``custom_sql``).

    A cheap pre-filter so a scan only parses the config of checks that can carry a reference, rather
    than every check on the team."""
    return _REFERENCING_CHECK_TYPES


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


def pin_referenced_subjects(team_id: int, check_type: str, config: dict[str, Any]) -> list[dict[str, str]] | None:
    """The identities of the subjects this run reads besides its own, to record alongside the run.

    Names cannot carry this. Deleting a warehouse object frees its name, so a recorded name starts
    naming whatever a member creates in its place, and history read back by name hands them what the
    run read over an object they were denied. An identity survives that: the reused name resolves to
    a different id, and the recorded id stops resolving.

    Every entry carries both keys and nothing else. The gate that reads these asks whether each entry
    is contained in the caller's readable set, and a partial entry is contained in more than it should
    be, so this shape is the guard.

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


def _readable_subject_q(readable: ReadableSubjects) -> Q:
    return Q(subject_type=SubjectType.TABLE, subject_uuid__in=readable.table_ids) | Q(
        subject_type=SubjectType.VIEW, subject_uuid__in=readable.view_ids
    )


def _readable_identities(readable: ReadableSubjects) -> list[dict[str, str]]:
    return [
        {_SUBJECT_TYPE_KEY: str(subject_type), _SUBJECT_UUID_KEY: str(subject_uuid)}
        for subject_type, ids in ((SubjectType.TABLE, readable.table_ids), (SubjectType.VIEW, readable.view_ids))
        for subject_uuid in ids
    ]


def _checks_whose_latest_run_is_unreadable(
    team_id: int, check_ids: Sequence[UUID], context: DenialContext
) -> set[UUID]:
    run_ids = latest_run_ids(team_id, check_ids)
    if not run_ids:
        return set()
    unreadable = (
        DataQualityCheckRun.objects.for_team(team_id)
        .filter(id__in=run_ids)
        .filter(unreadable_runs_q(context))
        .values_list("quality_check_id", flat=True)
    )
    return {check_id for check_id in unreadable if check_id is not None}


def _memoized_definition_verdict(
    team_id: int, check_type: str, config: dict[str, Any], context: DenialContext, verdicts: dict[str, bool]
) -> bool:
    key = json.dumps([check_type, config], sort_keys=True, default=str)
    if key not in verdicts:
        verdicts[key] = definition_reads_unreadable_subject(team_id, check_type, config, context)
    return verdicts[key]


def _pin_name(team_id: int, name: str) -> SubjectIdentity | None:
    ref = resolve_subject_by_name(team_id, name)
    if ref is None:
        return None
    return SubjectIdentity(subject_type=str(ref.subject_type), subject_uuid=ref.subject_uuid)
