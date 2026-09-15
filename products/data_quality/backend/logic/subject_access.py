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
from collections.abc import Callable, Collection, Sequence
from dataclasses import field
from itertools import batched
from typing import TYPE_CHECKING, Any, Optional, TypeVar
from uuid import UUID

from django.db.models import Exists, OuterRef, Q, QuerySet

from posthog.hogql.database.database import Database, system_table_denials
from posthog.hogql.database.schema.information_schema import DeniedTableMatcher

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.data_catalog.backend.facade import api as data_catalog_facade
from products.data_catalog.backend.facade.contracts import MetricSummary
from products.data_modeling.backend.facade import api as data_modeling_facade
from products.warehouse_sources.backend.facade import api as warehouse_facade

from ..facade.enums import SubjectType
from ..models import DataQualityCheck, DataQualityCheckRun
from .checks import latest_run_ids
from .contracts import SubjectIdentity, SubjectRef
from .exceptions import SubjectAccessUnverifiable
from .registry import all_specs, get_spec
from .spec import CheckTypeSpec
from .subjects import resolve_metric_subjects, resolve_subject, resolve_subject_by_name

if TYPE_CHECKING:
    from posthog.models import Team, User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

_SUBJECT_TYPE_KEY = "subject_type"
_SUBJECT_UUID_KEY = "subject_uuid"
_RunQS = TypeVar("_RunQS", bound=QuerySet)
_CHECK_VISIBILITY_BATCH_SIZE = 200
_CHECK_VISIBILITY_FIELDS = ("id", "subject_type", "table_id", "saved_query_id", "metric_id", "check_type", "config")


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
    metric_ids: frozenset[UUID] = frozenset()

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
        if subject_type == SubjectType.METRIC:
            return identifier in self.metric_ids
        return False


class DeferredDatabase:
    """The caller's HogQL database, built at most once and only if a verdict needs it.

    Only one question needs the whole HogQL name universe: whether a name a definition reads can be
    confirmed to resolve at all. Every other gate here is answered from identities and names, so a
    surface that asks none of them -- the run-history routes -- must not pay for a database holding
    every warehouse table of the team as a pydantic object.

    A plain class rather than a frozen dataclass, because it memoizes and :class:`DenialContext`
    stays frozen around it.
    """

    def __init__(self, build: Callable[[], Database]) -> None:
        self._build = build
        self._database: Database | None = None

    @classmethod
    def built(cls, database: Database) -> "DeferredDatabase":
        return cls(lambda: database)

    @classmethod
    def lazy(cls, build: Callable[[], Database]) -> "DeferredDatabase":
        return cls(build)

    def get(self) -> Database:
        if self._database is None:
            try:
                self._database = self._build()
            except Exception as err:
                capture_exception(err)
                raise SubjectAccessUnverifiable
        return self._database


@frozen
class DenialContext:
    """Everything a gate needs about one caller, resolved once and passed down.

    ``readable`` answers the identity-keyed questions a stored row asks, ``denied`` the name-keyed
    ones a definition asks, and ``database`` is the caller's own HogQL database -- deferred, so it
    is built only where a verdict needs it and a surface that has one already never builds a second.
    """

    readable: ReadableSubjects
    denied: set[str]
    database: DeferredDatabase
    metadata: "SubjectMetadata"
    matcher: DeniedTableMatcher = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "matcher", DeniedTableMatcher(self.denied))


@frozen
class NoticeReferences:
    """The subjects one notification's failure count says something about, besides its own subject.

    A ``custom_sql`` check reads whatever its query selects and a ``relationships`` check reads the
    table it points at, so the count is an oracle over those too. Resolved once per notice and held
    up against every recipient, because resolving a name to the object it reaches costs the same
    queries whoever is asking.

    ``identities`` are the subjects that resolve to a warehouse object, either pinned by the run or
    resolved from the definition's names. ``unresolved_names`` are the rest: ``system.*`` tables,
    PostHog tables, and names that no longer reach anything.
    """

    identities: tuple[SubjectIdentity, ...]
    unresolved_names: tuple[str, ...]


def notice_references(
    team_id: int, *, executed_references: Sequence[dict[str, str]] = (), names: Sequence[str] = ()
) -> NoticeReferences:
    """Resolve what a notice reads into identities, keeping the names that reach no object."""
    pinned = _pin_names(team_id, names)
    identities = [
        SubjectIdentity(subject_type=ref[_SUBJECT_TYPE_KEY], subject_uuid=ref[_SUBJECT_UUID_KEY])
        for ref in executed_references
    ]
    identities.extend(pinned.values())
    return NoticeReferences(
        identities=tuple(identities),
        unresolved_names=tuple(name for name in names if name not in pinned),
    )


@frozen
class ReferenceGate:
    """Decides whether one person may be told a check failed.

    Holds the two things that answer this over a :class:`NoticeReferences`: the subjects among those
    the person may read, and a matcher for the names they are denied.
    """

    readable: ReadableSubjects
    matcher: DeniedTableMatcher = field(compare=False)

    def admits(self, references: NoticeReferences) -> bool:
        if not all(self.readable.contains(ref.subject_type, ref.subject_uuid) for ref in references.identities):
            return False
        return not self.matcher.matches(references.unresolved_names)


def reference_gate(
    team: "Team",
    user: "User",
    user_access_control: "UserAccessControl",
    *,
    references: NoticeReferences,
    unentitled: Collection[str] | None = None,
) -> ReferenceGate:
    """One person's access to the subjects a single check reads. A few narrow queries, no build.

    Cost tracks what the check reads, not what the team owns, so a project with thousands of
    warehouse tables costs the same as one with three.
    """
    referenced: dict[str, set[UUID]] = {SubjectType.TABLE: set(), SubjectType.VIEW: set()}
    for reference in references.identities:
        # A run pins its references into an unrestricted JSON column, so one that does not parse is
        # left out of the lookup and fails closed in ``ReadableSubjects.contains``.
        if reference.subject_type in referenced and (identifier := _as_uuid(reference.subject_uuid)) is not None:
            referenced[reference.subject_type].add(identifier)
    return ReferenceGate(
        readable=ReadableSubjects(
            table_ids=warehouse_facade.allowed_table_ids(
                team.id, user_access_control, ids=referenced[SubjectType.TABLE]
            ),
            view_ids=data_modeling_facade.allowed_saved_query_ids(
                team.id, user_access_control, ids=referenced[SubjectType.VIEW]
            ),
        ),
        matcher=DeniedTableMatcher(system_table_denials(team, user, user_access_control, unentitled=unentitled)),
    )


@frozen
class SubjectMetadata:
    """The team's live subjects by id. ``table_keys`` is the dotted form a query writes."""

    table_names: dict[UUID, str]
    table_keys: dict[UUID, str]
    view_names: dict[UUID, str]
    metrics: tuple[MetricSummary, ...]


def subject_metadata(team_id: int) -> SubjectMetadata:
    tables = warehouse_facade.all_queryable_table_keys(team_id)
    excluded_table_ids = set(data_modeling_facade.backing_table_ids_by_saved_query(team_id))
    excluded_table_ids.update(warehouse_facade.direct_access_table_ids(team_id))
    included = {table_id: names for table_id, names in tables.items() if table_id not in excluded_table_ids}
    return SubjectMetadata(
        table_names={table_id: names.row_name for table_id, names in included.items()},
        table_keys={table_id: names.queryable_key for table_id, names in included.items()},
        view_names={
            UUID(view_id): name for view_id, name in data_modeling_facade.all_saved_query_names(team_id).items()
        },
        metrics=tuple(data_catalog_facade.live_metric_summaries(team_id)),
    )


def readable_subjects(
    team_id: int,
    denied: set[str],
    *,
    can_read_catalog: bool = True,
    metadata: SubjectMetadata | None = None,
) -> ReadableSubjects:
    """The team's live warehouse subjects, minus the ones this caller is denied. Four queries.

    Cost tracks the objects the team has, not the length of retained history, which is what makes
    it safe to hold a whole page of run history up against.
    """
    metadata = metadata if metadata is not None else subject_metadata(team_id)
    matcher = DeniedTableMatcher(denied)
    return ReadableSubjects(
        table_ids=frozenset(table_id for table_id, name in metadata.table_names.items() if not matcher.matches([name])),
        view_ids=frozenset(view_id for view_id, name in metadata.view_names.items() if not matcher.matches([name])),
        metric_ids=frozenset(
            metric.id
            for metric in metadata.metrics
            if can_read_catalog and not matcher.matches(metric.referenced_table_names)
        ),
    )


def unreachable_subject_names(
    team_id: int, user_access_control: Optional["UserAccessControl"], metadata: SubjectMetadata
) -> set[str]:
    """Every name this caller cannot reach, in both spellings a query can write.

    A source table answers to its row name and to its dotted key, and the gate that reads this
    matches leaf names, so recording only one of the two would let the other spelling through. No
    access-control context means nothing is reachable, which is how a service token fails closed.
    """
    allowed_tables = (
        warehouse_facade.allowed_table_ids(team_id, user_access_control)
        if user_access_control is not None
        else frozenset()
    )
    allowed_views = (
        data_modeling_facade.allowed_saved_query_ids(team_id, user_access_control)
        if user_access_control is not None
        else frozenset()
    )
    denied = {
        spelling
        for identifier, name in metadata.table_names.items()
        if identifier not in allowed_tables
        for spelling in (name, metadata.table_keys.get(identifier, name))
    }
    denied.update(name for identifier, name in metadata.view_names.items() if identifier not in allowed_views)
    return denied


def denial_context(team_id: int, database: Database, *, metadata: SubjectMetadata | None = None) -> DenialContext:
    """The caller's denial state, from a HogQL database that has already been built for them."""
    metadata = metadata if metadata is not None else subject_metadata(team_id)
    access = database.user_access_control
    denied = set(database._denied_tables) | unreachable_subject_names(team_id, access, metadata)
    can_read_catalog = access is not None and access.check_access_level_for_resource("data_catalog", "viewer")
    return DenialContext(
        readable=readable_subjects(
            team_id,
            denied,
            can_read_catalog=can_read_catalog,
            metadata=metadata,
        ),
        denied=denied,
        database=DeferredDatabase.built(database),
        metadata=metadata,
    )


def caller_denial_context(
    team: "Team",
    user: "User",
    user_access_control: "UserAccessControl",
    *,
    metadata: SubjectMetadata | None = None,
) -> DenialContext:
    """The caller's denial state, read from their grants. Defers the HogQL database build.

    The denial set a database would compute for this caller is the same object access check over the
    same objects, so it is derived here instead. The build is kept behind
    :class:`DeferredDatabase` for the one verdict that needs the whole name universe.
    """
    try:
        metadata = metadata if metadata is not None else subject_metadata(team.id)
        denied = set(system_table_denials(team, user, user_access_control))
        denied.update(unreachable_subject_names(team.id, user_access_control, metadata))
        readable = readable_subjects(
            team.id,
            denied,
            can_read_catalog=user_access_control.check_access_level_for_resource("data_catalog", "viewer"),
            metadata=metadata,
        )
    except Exception as err:
        # The snapshot walks every saved query; one malformed definition must not 500 the surface,
        # and failing open would leak denied subjects.
        capture_exception(err)
        raise SubjectAccessUnverifiable
    return DenialContext(
        readable=readable,
        denied=denied,
        database=DeferredDatabase.lazy(
            lambda: Database.create_for(team=team, user=user, user_access_control=user_access_control)
        ),
        metadata=metadata,
    )


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


def without_denied_runs(runs: _RunQS, context: DenialContext) -> _RunQS:
    """Exclude, in SQL, every run that touched a subject the caller may not read.

    A run is judged on the subjects its own columns record -- the one it declared and each it read --
    by the same rule the REST routes apply, so the two surfaces cannot come to different answers
    about the same run. Editing a check therefore cannot rewrite what its history discloses, and
    deleting a subject cannot free its name for something else to answer for it.

    Held up against a snapshot of the subjects the team has, so the cost tracks the warehouse rather
    than the length of retained history -- which matters here because this runs before the window
    that bounds the rows served.
    """
    return runs.exclude(unreadable_runs_q(context))


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
    hidden = definition_hidden_ids(team_id, checks, context, {})
    return hidden | _checks_whose_latest_run_is_unreadable(
        team_id, [check.id for check in checks if check.id not in hidden], context
    )


def definition_hidden_ids(
    team_id: int, checks: Sequence[DataQualityCheck], context: DenialContext, verdicts: dict[str, bool]
) -> set[UUID]:
    """The present-tense half of :func:`hidden_check_ids`: unreadable subject, or unreadable definition.

    ``verdicts`` is carried in by the caller so a scan that runs in batches parses a definition it has
    already seen once, whichever batch it lands in.
    """
    hidden = {check.id for check in checks if not context.readable.contains(check.subject_type, check.subject_uuid)}
    metric_subjects = resolve_metric_subjects(
        team_id,
        {
            UUID(str(check.metric_id))
            for check in checks
            if check.id not in hidden and check.subject_type == SubjectType.METRIC and check.metric_id is not None
        },
    )
    for check in checks:
        if check.id in hidden:
            continue
        subject = metric_subjects.get(UUID(str(check.metric_id))) if check.metric_id is not None else None
        if memoized_definition_verdict(team_id, check.check_type, check.config or {}, context, verdicts, subject):
            hidden.add(check.id)
    return hidden


def visible_checks(team_id: int, checks: Sequence[DataQualityCheck], context: DenialContext) -> list[DataQualityCheck]:
    """The checks a caller may see, by the same rule the REST surfaces apply.

    A check is out of reach on any of three counts: its own subject is unreadable, the definition it
    would run next reads one that is, or the run behind its ``last_status`` read one.
    """
    hidden = hidden_check_ids(team_id, checks, context)
    return [check for check in checks if check.id not in hidden]


def readable_check_subjects(
    queryset: QuerySet[DataQualityCheck], readable: ReadableSubjects
) -> QuerySet[DataQualityCheck]:
    return queryset.filter(
        Q(subject_type=SubjectType.TABLE, table_id__in=readable.table_ids)
        | Q(subject_type=SubjectType.VIEW, saved_query_id__in=readable.view_ids)
        | Q(subject_type=SubjectType.METRIC, metric_id__in=readable.metric_ids)
    )


def visible_check_queryset(
    team_id: int, queryset: QuerySet[DataQualityCheck], context: DenialContext
) -> QuerySet[DataQualityCheck]:
    queryset = readable_check_subjects(queryset, context.readable)
    candidates = queryset.select_related(None).prefetch_related(None).only(*_CHECK_VISIBILITY_FIELDS)
    hidden: set[UUID] = set()
    survivors: list[UUID] = []
    verdicts: dict[str, bool] = {}
    # The definition scan stays batched, because it holds a parsed config per row. The history scan
    # only needs ids, so it runs once over everything the definition scan let through rather than
    # once per batch.
    for batch in batched(
        candidates.iterator(chunk_size=_CHECK_VISIBILITY_BATCH_SIZE), _CHECK_VISIBILITY_BATCH_SIZE, strict=False
    ):
        batch_hidden = definition_hidden_ids(team_id, batch, context, verdicts)
        hidden |= batch_hidden
        survivors.extend(check.id for check in batch if check.id not in batch_hidden)
    hidden |= _checks_whose_latest_run_is_unreadable(team_id, survivors, context)
    return queryset.exclude(id__in=hidden)


def definition_reads_unreadable_subject(
    team_id: int, check_type: str, config: dict[str, Any], context: DenialContext, *, subject: SubjectRef | None = None
) -> bool:
    """Whether the definition a check would run next reads a subject beyond a caller's reach.

    The parent is not the only subject a check reads: a ``relationships`` check names a second
    subject and a ``custom_sql`` query selects arbitrary tables, both run by the worker with team
    scope only. Relationship targets are judged by their configured identity; custom SQL references
    are matched by name because the query names them rather than pinning them. A name that is denied,
    that no longer resolves, or that resolves to neither an allowed nor a denied object proves
    nothing in the caller's favor.
    """
    if not check_type_reads_beyond_subject(check_type):
        return False
    try:
        refs = referenced_subjects(team_id, check_type, config, subject=subject)
    except Exception as err:
        capture_exception(err)
        return True
    if refs.related_subject is not None and not context.readable.contains(
        refs.related_subject.subject_type, refs.related_subject.subject_uuid
    ):
        return True
    if context.matcher.matches(refs.names):
        return True
    return bool(unconfirmable_subject_names(refs.names, context.database.get()))


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
    if spec.reads_beyond_subject
    or type(spec).related_subject_ref is not CheckTypeSpec.related_subject_ref
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
    """What a check reads besides its declared subject, by name and configured identity.

    ``related_subject`` keeps a ``relationships`` target as the identity its config stores, so
    authorization does not need to resolve it through a mutable name."""

    names: tuple[str, ...]
    related_subject: SubjectIdentity | None


def referenced_subjects(
    team_id: int, check_type: str, config: dict[str, Any], *, subject: SubjectRef | None = None
) -> ReferencedSubjects:
    """Every warehouse name a check reads *besides* its declared subject.

    A ``relationships`` check names a second subject and a ``custom_sql`` query selects from arbitrary
    tables; the worker later runs both with team scope only. Authorizing these at the API is the one
    place a denied subject can be kept out of reach, so a check on an allowed subject can't be used as
    a count oracle over one the author cannot read. Assumes config already validated."""
    spec = get_spec(check_type)
    parsed = spec.parse_config(config)
    related_subject = (
        SubjectIdentity(subject_type=str(related[0]), subject_uuid=str(related[1]))
        if (related := spec.related_subject_ref(parsed))
        else None
    )
    names = spec.referenced_table_names(parsed, subject)
    return ReferencedSubjects(names=tuple(names), related_subject=related_subject)


def referenced_subject_names(
    team_id: int, check_type: str, config: dict[str, Any], *, subject: SubjectRef | None = None
) -> list[str]:
    """The names from :func:`referenced_subjects`, for callers that only report or match on them."""
    referenced = referenced_subjects(team_id, check_type, config, subject=subject)
    names = list(referenced.names)
    if referenced.related_subject is not None:
        related = resolve_subject(
            team_id, referenced.related_subject.subject_type, referenced.related_subject.subject_uuid
        )
        if related.exists:
            names.append(related.name)
    return names


def pin_referenced_subjects(
    team_id: int, check_type: str, config: dict[str, Any], *, subject: SubjectRef | None = None
) -> list[dict[str, str]] | None:
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
        references = referenced_subjects(team_id, check_type, config, subject=subject)
        if not references.names and references.related_subject is None:
            return []
        backing_tables = data_modeling_facade.backing_table_ids_by_saved_query(team_id)
        pinned = [
            identity for name in references.names if (identity := _pin_name(team_id, name, backing_tables)) is not None
        ]
        if references.related_subject is not None:
            pinned.append(references.related_subject)
    except Exception as err:
        capture_exception(err)
        return None
    return [{_SUBJECT_TYPE_KEY: subject.subject_type, _SUBJECT_UUID_KEY: subject.subject_uuid} for subject in pinned]


def _readable_subject_q(readable: ReadableSubjects) -> Q:
    return (
        Q(subject_type=SubjectType.TABLE, subject_uuid__in=readable.table_ids)
        | Q(subject_type=SubjectType.VIEW, subject_uuid__in=readable.view_ids)
        | Q(subject_type=SubjectType.METRIC, subject_uuid__in=readable.metric_ids)
    )


def _readable_identities(readable: ReadableSubjects) -> list[dict[str, str]]:
    return [
        {_SUBJECT_TYPE_KEY: str(subject_type), _SUBJECT_UUID_KEY: str(subject_uuid)}
        for subject_type, ids in (
            (SubjectType.TABLE, readable.table_ids),
            (SubjectType.VIEW, readable.view_ids),
            (SubjectType.METRIC, readable.metric_ids),
        )
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


def memoized_definition_verdict(
    team_id: int,
    check_type: str,
    config: dict[str, Any],
    context: DenialContext,
    verdicts: dict[str, bool],
    subject: SubjectRef | None = None,
) -> bool:
    # The subject enters the key as its identity: serializing the whole ref would drag a metric's
    # parsed HogQL definition into the hash of every row that shares it.
    identity = [subject.subject_type, subject.subject_uuid] if subject is not None else None
    key = json.dumps([check_type, config, identity], sort_keys=True, default=str)
    if key not in verdicts:
        verdicts[key] = definition_reads_unreadable_subject(team_id, check_type, config, context, subject=subject)
    return verdicts[key]


def _as_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _pin_names(team_id: int, names: Sequence[str]) -> dict[str, SubjectIdentity]:
    if not names:
        return {}
    backing_tables = data_modeling_facade.backing_table_ids_by_saved_query(team_id)
    pinned = ((name, _pin_name(team_id, name, backing_tables)) for name in names)
    return {name: identity for name, identity in pinned if identity is not None}


def _pin_name(team_id: int, name: str, backing_tables: dict[UUID, UUID]) -> SubjectIdentity | None:
    ref = resolve_subject_by_name(team_id, name)
    if ref is None:
        return None
    if ref.subject_type == SubjectType.TABLE and (saved_query_id := backing_tables.get(UUID(ref.subject_uuid))):
        return SubjectIdentity(subject_type=str(SubjectType.VIEW), subject_uuid=str(saved_query_id))
    return SubjectIdentity(subject_type=str(ref.subject_type), subject_uuid=ref.subject_uuid)
