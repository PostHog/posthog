from dataclasses import dataclass

from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


def jsonhas_expr(prop: str, param_prefix: str, column: str = "properties") -> str:
    """Build a ClickHouse ``JSONHas`` expression for a (possibly nested) property path.

    Splits dotted names so ``"sub.prop"`` becomes
    ``JSONHas(properties, %(prefix_0)s, %(prefix_1)s)``.  Pass ``column`` to
    target a different JSON column (e.g. ``"person_properties"``).
    """
    parts = prop.split(".")
    args = ", ".join(f"%({param_prefix}_{i})s" for i in range(len(parts)))
    return f"JSONHas({column}, {args})"


def compile_hogql_predicate(obj) -> tuple[str, dict]:
    """Parse and compile ``obj.hogql_predicate`` into a ClickHouse SQL fragment.

    Returns ``(sql_fragment, extra_params)``. Both are empty when the predicate
    is blank. The fragment excludes the surrounding parentheses so callers can
    decide how to splice it (typically ``AND (<fragment>)``). Raises
    :class:`~django.core.exceptions.ValidationError` on parse, resolution or
    subquery errors — suitable for use inside ``Model.clean()``.

    The fragment uses unqualified column references (no ``events.``/``sharded_events.``
    prefix), so it can be spliced into queries against either the Distributed
    ``events`` proxy or the local ``sharded_events`` MergeTree. This matters for
    lightweight DELETE: ClickHouse rewrites it into a mutation whose expression
    analyzer rejects table-qualified references like ``sharded_events.mat_$current_url``
    even when the column exists on every replica.
    """
    predicate = (getattr(obj, "hogql_predicate", "") or "").strip()
    if not predicate:
        return "", {}

    # Imported lazily: HogQL pulls in the full schema graph, which we don't want
    # to load for every model import (admin registration, migrations, etc.).
    from posthog.schema import PersonsOnEventsMode

    from posthog.hogql.context import HogQLContext
    from posthog.hogql.hogql import translate_hogql
    from posthog.hogql.modifiers import create_default_modifiers_for_team
    from posthog.hogql.parser import parse_expr

    from posthog.models.team import Team

    try:
        parse_expr(predicate)
    except Exception as exc:
        raise ValidationError({"hogql_predicate": f"Could not parse HogQL: {exc}"}) from exc

    if obj.team_id is None:
        raise ValidationError({"hogql_predicate": "team_id must be set before validating the predicate."})

    # Subqueries are allowed (e.g. ``person_id IN (SELECT id FROM persons WHERE …)``).
    # HogQL's table resolver injects ``team_id`` guards into each referenced table,
    # so cross-team data cannot leak through a subquery — the team-scoping test
    # in test_data_deletion_request.py is the regression net for that invariant.
    # ``within_non_hogql_query=True`` instructs the printer to emit unqualified column
    # references for the outer expression so the fragment splices into both the
    # Distributed ``events`` SELECT and the ``sharded_events`` DELETE mutation.
    #
    # Resolve the team's modifiers (``propertyGroupsMode`` et al.) so the predicate compiles
    # like a regular HogQL query. Without them the property-group optimizer is off, and a typed
    # property comparison such as ``person.properties.isEnterprise = 'yes'`` falls back to a
    # coerced JSONExtract that casts the value to Bool — turning the stored string into NULL so
    # the predicate silently matches nothing. With them it becomes the index-eligible
    # ``person_properties_map_custom['isEnterprise'] = 'yes'`` map read.
    #
    # Force on-events person resolution regardless of the team's general query default: the
    # fragment is spliced bare into the ``events`` SELECT and the ``sharded_events`` DELETE, so
    # ``person.properties`` must read the on-events ``person_properties`` column — a joined
    # persons table (the ``..._joined`` / ``disabled`` modes) would reference an alias that does
    # not exist in either splice site.
    try:
        team = Team.objects.get(id=obj.team_id)
    except Team.DoesNotExist as exc:
        raise ValidationError({"hogql_predicate": "team no longer exists; cannot validate the predicate."}) from exc
    modifiers = create_default_modifiers_for_team(team)
    modifiers.personsOnEventsMode = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
    context = HogQLContext(
        team_id=obj.team_id,
        team=team,
        modifiers=modifiers,
        within_non_hogql_query=True,
        enable_select_queries=True,
        # A deletion predicate must match rows regardless of retention; the events-retention floor would otherwise
        # narrow an events sub-query here and leave events older than the window un-deleted.
        apply_events_retention_floor=False,
    )
    try:
        sql = translate_hogql(predicate, context, dialect="clickhouse")
    except ImportError:
        # A failed import means the runtime environment is broken (e.g. a Dagster worker that
        # can't resolve ``common.hogvm`` during compilation), not that the predicate is invalid.
        # Let it propagate as-is rather than masquerading as a predicate validation error.
        raise
    except Exception as exc:
        raise ValidationError({"hogql_predicate": f"Could not compile HogQL: {exc}"}) from exc

    return sql, dict(context.values)


# Compiling a predicate builds the full HogQL schema graph, which is slow. The Django admin
# recompiles it on every stats/preview render, so cache the result in the shared Django cache
# (Redis). Keyed by request id and guarded by the predicate text it was compiled from, so a
# changed predicate never serves a stale fragment even if explicit invalidation is missed. The
# destructive Dagster deletion path deliberately calls ``compile_hogql_predicate`` directly
# (never this) so the actual mutation is always built from a freshly compiled predicate.
_COMPILED_PREDICATE_CACHE_PREFIX = "data_deletion:compiled_predicate:"
_COMPILED_PREDICATE_CACHE_TTL = 60 * 60 * 24  # 1 day; admin-only, a brief staleness window is fine


def _compiled_predicate_cache_key(request_id: object) -> str:
    return f"{_COMPILED_PREDICATE_CACHE_PREFIX}{request_id}"


def cached_compile_hogql_predicate(obj) -> tuple[str, dict]:
    """Cache-backed ``compile_hogql_predicate`` for the Django admin's stats/preview rendering.

    Only the informational admin path should use this. The Dagster deletion job compiles fresh via
    ``compile_hogql_predicate`` so the mutation is never built from a stale fragment.
    """
    predicate = (getattr(obj, "hogql_predicate", "") or "").strip()
    if not predicate:
        return "", {}
    request_id = getattr(obj, "pk", None) or getattr(obj, "request_id", None)
    if request_id is None:
        return compile_hogql_predicate(obj)
    key = _compiled_predicate_cache_key(request_id)
    cached = cache.get(key)
    if cached is not None and cached.get("source") == predicate:
        return cached["sql"], cached["params"]
    sql, params = compile_hogql_predicate(obj)
    cache.set(key, {"source": predicate, "sql": sql, "params": params}, _COMPILED_PREDICATE_CACHE_TTL)
    return sql, params


def invalidate_compiled_predicate_cache(request_id: object) -> None:
    """Drop the cached compiled predicate. Called when a request's deletion criteria change."""
    cache.delete(_compiled_predicate_cache_key(request_id))


def event_match_sql_fragment(obj) -> str:
    """WHERE fragment that narrows to the matching event names.

    Returns an empty string when ``obj.delete_all_events`` is set, so callers can
    drop the ``event IN %(events)s`` filter without special-casing. Accepts both
    the Django model and the Dagster ``DeletionRequestContext`` dataclass.
    """
    if getattr(obj, "delete_all_events", False):
        return ""
    return "AND event IN %(events)s"


def event_match_params(obj) -> dict:
    """Params for the time-bounded event match (omits ``events`` when deleting all)."""
    params: dict = {
        "team_id": obj.team_id,
        "start_time": obj.start_time,
        "end_time": obj.end_time,
    }
    if not getattr(obj, "delete_all_events", False):
        params["events"] = obj.events
    return params


_EVENT_REMOVAL_TIME_PREDICATE = "team_id = %(team_id)s AND timestamp >= %(start_time)s AND timestamp < %(end_time)s"


def event_removal_where(obj) -> tuple[str, dict]:
    """Full WHERE predicate + params for event-removal queries.

    Combines the mandatory team/timestamp bounds, the events filter (skipped
    when ``delete_all_events`` is set), and any compiled HogQL predicate. The
    compiled HogQL fragment uses unqualified column references, so the result
    is safe to splice into queries against either the Distributed ``events``
    proxy or the local ``sharded_events`` MergeTree.
    """
    parts = [_EVENT_REMOVAL_TIME_PREDICATE, event_match_sql_fragment(obj)]
    params = event_match_params(obj)
    hogql_sql, hogql_values = compile_hogql_predicate(obj)
    if hogql_sql:
        parts.append(f"AND ({hogql_sql})")
        params.update(hogql_values)
    return " ".join(p for p in parts if p), params


class RequestType(models.TextChoices):
    PROPERTY_REMOVAL = "property_removal"
    EVENT_REMOVAL = "event_removal"
    PERSON_REMOVAL = "person_removal"


class RequestStatus(models.TextChoices):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionMode(models.TextChoices):
    IMMEDIATE = "immediate"
    DEFERRED = "deferred"


class DataDeletionRequest(UUIDModel):
    # Request config
    team_id = models.IntegerField()
    request_type = models.CharField(
        max_length=40,
        choices=RequestType.choices,
        help_text="property_removal: remove specific properties from matching events. "
        "event_removal: delete entire events matching the criteria.",
    )
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)

    events = ArrayField(
        models.CharField(max_length=1024),
        blank=True,
        default=list,
        help_text="Event names to match. May be empty only when delete_all_events is true.",
    )
    delete_all_events = models.BooleanField(
        default=False,
        help_text="Opt in to matching every event for the team in the given time range. "
        "For event_removal this deletes every event; for property_removal it removes the "
        "property from every event. Not valid for person_removal. Requires events to be empty.",
    )
    hogql_predicate = models.TextField(
        blank=True,
        default="",
        help_text="Optional HogQL boolean expression to further narrow matching events. "
        "Validated against the events table at save time. Combined with the other "
        "filters (team/timestamp/events) via AND. Example: "
        "properties.$browser = 'Chrome'.",
    )
    properties = ArrayField(
        models.CharField(max_length=1024),
        blank=True,
        default=list,
        help_text="Property names to remove from events.properties. Required for property_removal requests when person_properties is empty.",
    )
    person_properties = ArrayField(
        models.CharField(max_length=1024),
        blank=True,
        null=True,
        default=list,
        help_text="Property names to remove from events.person_properties. Required for property_removal requests when properties is empty.",
    )
    person_uuids = ArrayField(
        models.UUIDField(),
        blank=True,
        default=list,
        help_text="Person UUIDs to target. Mutually exclusive with person_distinct_ids; max 1000.",
    )
    person_distinct_ids = ArrayField(
        models.CharField(max_length=400),
        blank=True,
        default=list,
        help_text="Person distinct IDs to target. Mutually exclusive with person_uuids; max 1000.",
    )
    person_drop_profiles = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Drop person profiles (Postgres + ClickHouse tombstone). NULL when not a person_removal request.",
    )
    person_drop_events = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Drop event records linked to these persons. NULL when not a person_removal request.",
    )
    person_drop_recordings = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Drop session recordings linked to these persons. NULL when not a person_removal request.",
    )

    status = models.CharField(max_length=40, choices=RequestStatus.choices, default=RequestStatus.DRAFT)

    # Stats (populated by ClickHouse query)
    count = models.BigIntegerField(null=True, blank=True, help_text="Number of events matching criteria")
    part_count = models.IntegerField(null=True, blank=True, help_text="Number of ClickHouse parts")
    parts_size = models.BigIntegerField(null=True, blank=True)
    parts_row_count = models.BigIntegerField(null=True, blank=True)
    min_timestamp = models.DateTimeField(null=True, blank=True, help_text="Earliest timestamp of matching events.")
    max_timestamp = models.DateTimeField(null=True, blank=True, help_text="Latest timestamp of matching events.")
    stats_calculated_at = models.DateTimeField(null=True, blank=True)

    # Metadata
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="data_deletion_requests_created",
    )
    created_by_staff = models.BooleanField(null=True, blank=True, help_text="Was this created by instance operator.")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    criteria_updated_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_deletion_requests_criteria_updated",
        help_text="Last user who changed deletion criteria (events, properties, time range, or request type).",
    )
    criteria_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When deletion criteria were last changed.",
    )

    # Approval workflow
    requires_approval = models.BooleanField(
        default=True,
        help_text="ClickHouse deletes are heavyweight mutations that can degrade query performance "
        "and increase disk usage while running. Approval ensures deletes are scheduled "
        "during low-traffic windows to avoid impacting production workloads.",
    )
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="data_deletion_requests_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    execution_mode = models.CharField(
        max_length=20,
        choices=ExecutionMode.choices,
        default=ExecutionMode.IMMEDIATE,
        help_text="Picked by ClickHouse Team at approval time. "
        "Immediate: run a dedicated delete mutation now. "
        "Deferred: queue event UUIDs into adhoc_events_deletion so the "
        "scheduled deletes_job drains them. Only honored for event_removal.",
    )

    # Execution tracking
    attempt_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of times execution has been attempted. "
        "Incremented when a load_* op transitions the request to IN_PROGRESS.",
    )
    first_executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When execution was first attempted (set on the first APPROVED → IN_PROGRESS transition).",
    )
    last_executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When execution was most recently attempted (updated on every APPROVED → IN_PROGRESS transition).",
    )

    # The team_id this request was loaded from the DB with (None until loaded). Set by from_db so
    # clean() can reject retargeting an existing request at a different team. Not a model field.
    _loaded_team_id: int | None = None

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"DataDeletionRequest({self.request_type}, team={self.team_id}, status={self.status})"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_team_id = instance.team_id
        return instance

    def clean(self) -> None:
        super().clean()
        if self._loaded_team_id is not None and self.team_id != self._loaded_team_id:
            raise ValidationError({"team_id": "team_id cannot be changed after the request is created."})
        if self.request_type == RequestType.EVENT_REMOVAL:
            self._clean_event_removal()
        elif self.request_type == RequestType.PROPERTY_REMOVAL:
            self._clean_property_removal()
        elif self.request_type == RequestType.PERSON_REMOVAL:
            self._clean_person_removal()
            return  # PERSON_REMOVAL never has hogql_predicate / events / properties
        else:
            raise ValidationError({"request_type": f"Unknown request_type: {self.request_type}"})

        # delete_all_events is valid for event_removal and property_removal; person_removal rejects it
        # in _clean_person_removal and returns above before reaching here.
        if self.hogql_predicate:
            compile_hogql_predicate(self)

    def _clean_event_removal(self) -> None:
        self._require_time_range()
        self._validate_event_scope(verb="delete")
        self._reject_person_fields()

    def _clean_property_removal(self) -> None:
        self._require_time_range()
        self._validate_event_scope(verb="match")
        self._reject_person_fields()

    def _validate_event_scope(self, *, verb: str) -> None:
        if self.delete_all_events and self.events:
            raise ValidationError({"events": "Events must be empty when delete_all_events is set."})
        if not self.delete_all_events and not self.events:
            raise ValidationError(
                {"events": f"Provide at least one event, or set delete_all_events to {verb} every event."}
            )

    def _require_time_range(self) -> None:
        if self.start_time is None or self.end_time is None:
            raise ValidationError({"start_time": "start_time and end_time are required for event/property removal."})
        if self.start_time >= self.end_time:
            raise ValidationError({"start_time": "start_time must be before end_time."})

    def _clean_person_removal(self) -> None:
        if self.person_uuids and self.person_distinct_ids:
            raise ValidationError({"person_uuids": "Provide either person_uuids or person_distinct_ids, not both."})
        total = len(self.person_uuids) + len(self.person_distinct_ids)
        if total == 0:
            raise ValidationError({"person_uuids": "Provide at least one person_uuid or person_distinct_id."})
        if total > 1000:
            raise ValidationError({"person_uuids": "person_uuids or person_distinct_ids must be ≤ 1000."})
        if not (self.person_drop_profiles or self.person_drop_events or self.person_drop_recordings):
            raise ValidationError(
                {"person_drop_profiles": "At least one of person_drop_profiles / events / recordings must be true."}
            )
        if self.events or self.delete_all_events:
            raise ValidationError({"events": "events / delete_all_events are not valid for person_removal."})
        if self.properties:
            raise ValidationError({"properties": "properties are not valid for person_removal."})
        if self.person_properties:
            raise ValidationError({"person_properties": "person_properties are not valid for person_removal."})
        if self.hogql_predicate:
            raise ValidationError({"hogql_predicate": "hogql_predicate is not valid for person_removal."})

    def _reject_person_fields(self) -> None:
        if self.person_uuids or self.person_distinct_ids:
            raise ValidationError(
                {"person_uuids": "person_uuids / person_distinct_ids are only valid for person_removal."}
            )
        if self.person_drop_profiles or self.person_drop_events or self.person_drop_recordings:
            raise ValidationError({"person_drop_profiles": "person_drop_* flags are only valid for person_removal."})


def count_remaining_matching_events(request: "DataDeletionRequest") -> int:
    """Count events still matching an event-removal request's criteria in ClickHouse."""
    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.client.connection import ClickHouseUser
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context
    from posthog.clickhouse.workload import Workload

    predicate, params = event_removal_where(request)
    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=request.team_id,
        workload=Workload.OFFLINE,
        query_type="data_deletion_request_verify_queued",
    ):
        # nosemgrep: clickhouse-fstring-param-audit (predicate built from internal helper, not user input)
        result = sync_execute(
            f"SELECT count() FROM events WHERE {predicate} AND _row_exists = 1",
            params,
            team_id=request.team_id,
            readonly=True,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.META,
        )
    return int(result[0][0]) if result else 0


@dataclass
class VerifyOutcome:
    remaining: int
    promoted: bool


# Statuses from which verification may promote an event-removal request to COMPLETED. QUEUED is the
# normal deferred path; FAILED is included so the ClickHouse Team can confirm a request whose job
# errored after the events were actually deleted (e.g. a failure in the finalize step) without
# re-running the whole deletion.
VERIFIABLE_STATUSES = (RequestStatus.QUEUED, RequestStatus.FAILED)


def verify_queued_request(request: "DataDeletionRequest") -> VerifyOutcome:
    """Verify an event-removal request and promote it to COMPLETED when its events are gone.

    Counts events still matching the request in ClickHouse. When zero remain and the request is in a
    verifiable status (QUEUED or FAILED), atomically promotes it to COMPLETED via a status-guarded
    update. Idempotent; safe to call from both the Dagster sweep job and the Django admin button.
    """
    remaining = count_remaining_matching_events(request)
    if remaining > 0 or request.status not in VERIFIABLE_STATUSES:
        return VerifyOutcome(remaining=remaining, promoted=False)
    promoted = DataDeletionRequest.objects.filter(pk=request.pk, status__in=VERIFIABLE_STATUSES).update(
        status=RequestStatus.COMPLETED, updated_at=timezone.now()
    )
    return VerifyOutcome(remaining=remaining, promoted=bool(promoted))
