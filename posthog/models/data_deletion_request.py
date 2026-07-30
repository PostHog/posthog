from collections.abc import Callable
from dataclasses import dataclass

from django.contrib.postgres.fields import ArrayField
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F
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


def compile_hogql_predicate(obj, use_new_events_schema: bool = False) -> tuple[str, dict]:
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

    ``use_new_events_schema`` compiles property access for the native-JSON events tables
    (``events_json`` / ``sharded_events_json``) — JSON subcolumn reads instead of
    JSONExtract/materialized-column reads. Deletions target both physical events tables, so
    callers compile one fragment per table.
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
        sql = translate_hogql(
            predicate,
            context,
            dialect="clickhouse",
            events_table_use_new_schema=use_new_events_schema,
        )
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


def event_removal_where(obj, use_new_events_schema: bool = False) -> tuple[str, dict]:
    """Full WHERE predicate + params for event-removal queries.

    Combines the mandatory team/timestamp bounds, the events filter (skipped
    when ``delete_all_events`` is set), and any compiled HogQL predicate. The
    compiled HogQL fragment uses unqualified column references, so the result
    is safe to splice into queries against either the Distributed ``events``
    proxy or the local ``sharded_events`` MergeTree. Pass ``use_new_events_schema``
    when the query targets the native-JSON events tables.
    """
    parts = [_EVENT_REMOVAL_TIME_PREDICATE, event_match_sql_fragment(obj)]
    params = event_match_params(obj)
    hogql_sql, hogql_values = compile_hogql_predicate(obj, use_new_events_schema=use_new_events_schema)
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
        help_text="Force manual ClickHouse Team approval, opting out of auto-approval. "
        "ClickHouse deletes are heavyweight mutations that can degrade query performance "
        "and increase disk usage while running, so approval ensures they are scheduled "
        "during low-traffic windows. Small event_removal requests are cheap enough to skip "
        "that review, so the auto-approval sweep job approves them unless this is set. "
        "Written by the submit page only.",
    )
    approved = models.BooleanField(default=False)
    approved_automatically = models.BooleanField(
        default=False,
        help_text="Approved by the auto-approval sweep job rather than a person. approved_by is NULL for these.",
    )
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
    last_dagster_run_id = models.CharField(
        # Dagster run ids are UUIDs, but keep headroom: this is written by the same save() that marks
        # the request IN_PROGRESS, so an over-long id would fail the whole deletion job over a field
        # that only exists to make debugging easier.
        max_length=255,
        null=True,
        blank=True,
        help_text="Dagster run ID of the most recent execution attempt (set on every APPROVED → IN_PROGRESS "
        "transition). Rendered as a link to the Dagster run in the admin.",
    )
    property_removal_marker = models.DateTimeField(
        null=True,
        blank=True,
        help_text="inserted_at/_timestamp stamp applied to cleaned re-inserts of this property_removal "
        "request. Set once on the first execution attempt and reused by every retry so re-runs recognize "
        "already-cleaned rows and never insert a second copy. Cleared when deletion criteria change.",
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


def _append_hogql_predicate(fragment: str, params: dict, obj) -> tuple[str, dict]:
    """Append the compiled HogQL predicate (if any) to ``fragment`` and merge params."""
    hogql_sql, hogql_values = cached_compile_hogql_predicate(obj)
    if not hogql_sql:
        return fragment, params
    combined = f"{fragment} AND ({hogql_sql})".strip() if fragment else f"AND ({hogql_sql})"
    params.update(hogql_values)
    return combined, params


def _build_event_filter(obj) -> tuple[str, dict]:
    """Build the WHERE clause and params for matching events."""
    return _append_hogql_predicate(event_match_sql_fragment(obj), event_match_params(obj), obj)


def _build_property_filter(obj) -> tuple[str, dict]:
    """Build the WHERE clause addition and params for matching properties.

    Covers both ``events.properties`` (using ``fp_`` param prefix) and
    ``events.person_properties`` (using ``pp_`` param prefix).  The two
    presence checks are ORed so the stats count includes every event that
    carries at least one target key in either column.
    """
    event_clause = event_match_sql_fragment(obj)
    params: dict = event_match_params(obj)

    presence_clauses: list[str] = []

    properties = obj.properties or []
    if properties:
        if len(properties) == 1:
            presence_clauses.append(jsonhas_expr(properties[0], "fp_0"))
        else:
            exprs = [jsonhas_expr(prop, f"fp_{i}") for i, prop in enumerate(properties)]
            presence_clauses.append(f"({' OR '.join(exprs)})")
        for i, prop in enumerate(properties):
            for j, part in enumerate(prop.split(".")):
                params[f"fp_{i}_{j}"] = part

    person_properties = obj.person_properties or []
    if person_properties:
        if len(person_properties) == 1:
            presence_clauses.append(jsonhas_expr(person_properties[0], "pp_0", column="person_properties"))
        else:
            exprs = [
                jsonhas_expr(prop, f"pp_{i}", column="person_properties") for i, prop in enumerate(person_properties)
            ]
            presence_clauses.append(f"({' OR '.join(exprs)})")
        for i, prop in enumerate(person_properties):
            for j, part in enumerate(prop.split(".")):
                params[f"pp_{i}_{j}"] = part

    if not presence_clauses:
        raise ValueError("Cannot build property filter: both properties and person_properties are empty.")

    property_clause = (
        f"AND ({' OR '.join(presence_clauses)})" if len(presence_clauses) > 1 else f"AND {presence_clauses[0]}"
    )
    filter_clause = f"{event_clause} {property_clause}".strip()
    return _append_hogql_predicate(filter_clause, params, obj)


def _event_count_query_template(extra_filter: str) -> str:
    # Counts run against the distributed ``events`` table so operators get a
    # cluster-wide number; the actual deletions still target ``sharded_events``.
    # nosemgrep: clickhouse-fstring-param-audit (extra_filter is built from internal helpers, not user input)
    return f"""
            SELECT
                count() AS events,
                count(DISTINCT _part) AS parts,
                min(timestamp) AS min_ts,
                max(timestamp) AS max_ts
            FROM events
            WHERE team_id = %(team_id)s
              AND timestamp >= %(start_time)s
              AND timestamp < %(end_time)s
              {extra_filter}
            """


def build_deletion_count_query(obj: "DataDeletionRequest") -> tuple[str, dict]:
    """Return the (SQL template, params) used to count rows matching this request.

    Mirrors ``_fetch_stats`` so admin users can copy the query and run it
    independently — ``substitute_params_for_display`` is the companion renderer.
    """
    if obj.request_type == RequestType.PROPERTY_REMOVAL:
        extra_filter, params = _build_property_filter(obj)
    else:
        extra_filter, params = _build_event_filter(obj)
    return _event_count_query_template(extra_filter), params


_STATS_MAX_EXECUTION_TIME = 300


def _fetch_stats(team_id: int, extra_filter: str, params: dict, *, user_id: int | None = None) -> dict:
    """Run event count + parts size queries against ClickHouse.

    The same predicate is spliced into both queries: the row count against the
    Distributed ``events`` proxy, and the parts inspection against the local
    ``sharded_events``. The HogQL predicate emits unqualified column references,
    so it works in both contexts.

    ``user_id`` is threaded into the query tag so the acting staff user is
    visible in ``system.query_log`` (the kill-switch + tag annotator pick it up
    automatically via :class:`QueryTags`). The auto-approval sweep job has no
    acting user and passes None.
    """
    from django.conf import settings as django_settings

    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.client.connection import ClickHouseUser
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context
    from posthog.clickhouse.workload import Workload

    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=team_id,
        user_id=user_id,
        workload=Workload.OFFLINE,
        query_type="delete_event_count",
    ):
        event_result = sync_execute(
            _event_count_query_template(extra_filter),
            params,
            team_id=team_id,
            readonly=True,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.META,
            settings={"max_execution_time": _STATS_MAX_EXECUTION_TIME},
        )

    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=team_id,
        user_id=user_id,
        workload=Workload.OFFLINE,
        query_type="delete_part_count",
    ):
        cluster = django_settings.CLICKHOUSE_CLUSTER

        # nosemgrep: clickhouse-fstring-param-audit (filter built from internal helpers; cluster from Django settings)
        parts_result = sync_execute(
            f"""
            SELECT
                count() AS part_count,
                sum(p.bytes_on_disk) AS total_size_on_disk,
                sum(p.rows) AS total_rows_in_those_parts
            FROM cluster('{cluster}', system, parts) AS p
            INNER JOIN (
                SELECT DISTINCT _part AS name
                FROM sharded_events
                WHERE team_id = %(team_id)s
                  AND timestamp >= %(start_time)s
                  AND timestamp < %(end_time)s
                  {extra_filter}
            ) AS matched ON p.name = matched.name
            WHERE p.table = 'sharded_events'
              AND p.active
            """,
            params,
            team_id=team_id,
            readonly=True,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.META,
            settings={"max_execution_time": _STATS_MAX_EXECUTION_TIME},
        )

    return {
        "count": event_result[0][0] if event_result else 0,
        "min_timestamp": event_result[0][2] if event_result and event_result[0][0] else None,
        "max_timestamp": event_result[0][3] if event_result and event_result[0][0] else None,
        "part_count": parts_result[0][0] if parts_result else 0,
        "parts_size": parts_result[0][1] if parts_result else 0,
        "parts_row_count": parts_result[0][2] if parts_result else 0,
    }


def fetch_event_deletion_stats(obj: "DataDeletionRequest", *, user_id: int | None = None) -> dict:
    """Count events and affected parts for an event removal request."""
    extra_filter, params = _build_event_filter(obj)
    return _fetch_stats(obj.team_id, extra_filter, params, user_id=user_id)


def fetch_property_deletion_stats(obj: "DataDeletionRequest", *, user_id: int | None = None) -> dict:
    """Count events with matching properties and affected parts for a property removal request."""
    if not obj.properties and not obj.person_properties:
        raise ValueError(
            "Cannot fetch stats for a property removal request with no properties or person_properties specified."
        )
    extra_filter, params = _build_property_filter(obj)
    return _fetch_stats(obj.team_id, extra_filter, params, user_id=user_id)


def fetch_deletion_stats(obj: "DataDeletionRequest", *, user_id: int | None = None) -> dict:
    """Dispatch to the appropriate stats function based on request type."""
    if obj.request_type == RequestType.PROPERTY_REMOVAL:
        return fetch_property_deletion_stats(obj, user_id=user_id)
    return fetch_event_deletion_stats(obj, user_id=user_id)


# The fields ``_fetch_stats`` populates, in the order the model declares them. Both writers — the
# admin's Fetch stats button and the auto-approval sweep job — save exactly this set, so a new stat
# can't reach one path and silently skip the other.
STATS_FIELDS = (
    "count",
    "part_count",
    "parts_size",
    "parts_row_count",
    "min_timestamp",
    "max_timestamp",
)


class StaleDeletionRequestError(Exception):
    """The request changed while its stats were being computed, so they were not written."""


def refresh_deletion_stats(request: "DataDeletionRequest", *, user_id: int | None = None) -> dict:
    """Fetch this request's ClickHouse stats and persist them onto the row.

    The counting query takes seconds to minutes, and the write is guarded on ``updated_at`` for that
    window. Changing a request's criteria clears its stats precisely because the old numbers no longer
    describe it, so writing ours back over that edit would resurrect a count for criteria nobody
    measured — one a reviewer could then approve against. Every write to the row bumps ``updated_at``
    (``auto_now``), so a mismatch means the request moved and this fetch is void.
    """
    stats = fetch_deletion_stats(request, user_id=user_id)
    now = timezone.now()
    updated = DataDeletionRequest.objects.filter(pk=request.pk, updated_at=request.updated_at).update(
        stats_calculated_at=now,
        updated_at=now,
        **{field: stats[field] for field in STATS_FIELDS},
    )
    if not updated:
        raise StaleDeletionRequestError(
            f"Deletion request {request.pk} changed while its stats were being computed. Try again."
        )
    request.refresh_from_db()
    return stats


def count_remaining_matching_events(request: "DataDeletionRequest") -> int:
    """Count events still matching an event-removal request's criteria in ClickHouse.

    Counts across every events read table (legacy and native-JSON) — a request is only complete
    once its events are gone from all of them.
    """
    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.client.connection import ClickHouseUser
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context
    from posthog.clickhouse.workload import Workload
    from posthog.models.event.deletion import events_read_tables_via_sync_execute
    from posthog.models.event.sql import DISTRIBUTED_EVENTS_JSON_TABLE

    total = 0
    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=request.team_id,
        workload=Workload.OFFLINE,
        query_type="data_deletion_request_verify_queued",
    ):
        for table in events_read_tables_via_sync_execute():
            predicate, params = event_removal_where(
                request, use_new_events_schema=table == DISTRIBUTED_EVENTS_JSON_TABLE
            )
            # nosemgrep: clickhouse-fstring-param-audit (predicate built from internal helper, not user input)
            result = sync_execute(
                f"SELECT count() FROM {table} WHERE {predicate} AND _row_exists = 1",
                params,
                team_id=request.team_id,
                readonly=True,
                workload=Workload.OFFLINE,
                ch_user=ClickHouseUser.META,
            )
            total += int(result[0][0]) if result else 0
    return total


def _mat_col_presence_clauses(mat_cols: list[tuple[str, bool]]) -> list[str]:
    """ "Value is present" checks for DEFAULT-materialized property columns: ``col != ''``.

    Matches the deletion path in posthog/dags/data_deletion_requests.py: the DEFAULT expression
    stores ``''`` for missing keys, so ``!= ''`` (not ``IS NOT NULL``) is the correct presence test.
    """
    return [f"`{name}` != ''" for name, _ in mat_cols]


def discover_affected_mat_columns(properties: list[str], table_column: str) -> list[tuple[str, bool]]:
    """DEFAULT-materialized columns on the distributed ``events`` table for the given properties.

    Returns ``(column_name, is_nullable)`` for columns whose comment follows the
    ``column_materializer::<table_column>::<prop>`` convention. Mirrors ``_get_affected_mat_columns``
    in the deletion job so verification counts a row as dirty on the same terms the deletion does — a
    value left in a materialized column after its JSON key is gone still counts.
    """
    if not properties:
        return []

    from django.conf import settings as django_settings

    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.client.connection import ClickHouseUser

    from ee.clickhouse.materialized_columns.columns import MaterializedColumnDetails

    rows = sync_execute(
        """
        SELECT name, comment, type LIKE 'Nullable(%%)'
        FROM system.columns
        WHERE database = %(database)s
          AND table = 'events'
          AND comment LIKE '%%column_materializer::%%'
          AND comment NOT LIKE '%%column_materializer::elements_chain::%%'
        """,
        {"database": django_settings.CLICKHOUSE_DATABASE},
        readonly=True,
        ch_user=ClickHouseUser.META,
    )
    target = set(properties)
    result: list[tuple[str, bool]] = []
    for name, comment, is_nullable in rows:
        details = MaterializedColumnDetails.from_column_comment(comment)
        if details.table_column == table_column and details.property_name in target:
            result.append((name, bool(is_nullable)))
    return result


def _property_presence_where(
    request: "DataDeletionRequest",
    mat_cols: list[tuple[str, bool]] | None = None,
    person_mat_cols: list[tuple[str, bool]] | None = None,
) -> tuple[str, dict]:
    """WHERE predicate + params matching events that still carry any target (person_)property.

    Mirrors ``event_removal_where`` but swaps the events filter for a presence check over
    ``properties`` / ``person_properties`` and their DEFAULT-materialized columns. Used to verify a
    property_removal request: once the property has been stripped from the JSON and its materialized
    column reset on every matching event, this count reaches zero. The presence set must match the
    deletion path (``_property_removal_where``) or a row it still considers dirty reads as clean here.
    """
    parts = [_EVENT_REMOVAL_TIME_PREDICATE, event_match_sql_fragment(request)]
    params = event_match_params(request)

    presence: list[str] = []
    for i, prop in enumerate(request.properties or []):
        presence.append(jsonhas_expr(prop, f"fp_{i}"))
        for j, part in enumerate(prop.split(".")):
            params[f"fp_{i}_{j}"] = part
    if mat_cols:
        presence.extend(_mat_col_presence_clauses(mat_cols))
    for i, prop in enumerate(request.person_properties or []):
        presence.append(jsonhas_expr(prop, f"pp_{i}", column="person_properties"))
        for j, part in enumerate(prop.split(".")):
            params[f"pp_{i}_{j}"] = part
    if person_mat_cols:
        presence.extend(_mat_col_presence_clauses(person_mat_cols))
    if presence:
        parts.append(f"AND ({' OR '.join(presence)})")

    hogql_sql, hogql_values = compile_hogql_predicate(request)
    if hogql_sql:
        parts.append(f"AND ({hogql_sql})")
        params.update(hogql_values)
    return " ".join(p for p in parts if p), params


def count_remaining_property_events(request: "DataDeletionRequest") -> int:
    """Count events that still carry any of a property-removal request's target properties."""
    from posthog.clickhouse.client import sync_execute
    from posthog.clickhouse.client.connection import ClickHouseUser
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context
    from posthog.clickhouse.workload import Workload

    mat_cols = discover_affected_mat_columns(request.properties or [], "properties")
    person_mat_cols = discover_affected_mat_columns(request.person_properties or [], "person_properties")
    predicate, params = _property_presence_where(request, mat_cols, person_mat_cols)
    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=request.team_id,
        workload=Workload.OFFLINE,
        query_type="data_deletion_request_verify_property",
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


def count_remaining_for_request(request: "DataDeletionRequest") -> int | None:
    """Count rows still matching a deletion request's criteria in ClickHouse.

    Dispatches on request type: matching events for event_removal, events still carrying the
    target property for property_removal. Returns ``None`` for person_removal, which has no
    automated remaining-count.
    """
    if request.request_type == RequestType.EVENT_REMOVAL:
        return count_remaining_matching_events(request)
    if request.request_type == RequestType.PROPERTY_REMOVAL:
        return count_remaining_property_events(request)
    return None


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


# An event removal below this many events is cheap enough that a dedicated ClickHouse Team review buys
# nothing. The sweep job approves it instead, always deferred so the scheduled deletes_job drains it
# alongside everything else rather than running a mutation of its own.
AUTO_APPROVE_MAX_EVENTS = 100_000
# How often the sweep job runs. Lives here rather than beside the schedule so the admin can tell an
# operator how long their request will sit before it's looked at, without the two drifting apart.
AUTO_APPROVE_INTERVAL_MINUTES = 30


def auto_approve_blocker(request: "DataDeletionRequest") -> str | None:
    """Why this pending request can't be auto-approved, or None when it can.

    Called by the sweep job immediately after it refreshes the request's stats, so ``count`` is
    current by construction — there is no staleness to defend against here.

    ``requires_approval`` and ``status`` are deliberately not checked: they narrow which requests the
    job considers at all (a queryset filter) and guard the write (a status-guarded update), rather
    than describing whether this request is small enough to skip review.
    """
    if request.request_type != RequestType.EVENT_REMOVAL:
        return (
            f"only event removal requests can be auto-approved, and this is a "
            f"{request.get_request_type_display().lower()} request"
        )
    # A range that hasn't closed keeps matching newly ingested events, so a count taken now says
    # nothing about how much the deferred job will actually delete when it drains later.
    if request.end_time is None or request.end_time > timezone.now():
        return "its time range has not closed yet, so matching events are still arriving"
    if request.count is None:
        return "the stats refresh produced no matching event count"
    if request.count >= AUTO_APPROVE_MAX_EVENTS:
        return f"{request.count:,} matching events is at or above the {AUTO_APPROVE_MAX_EVENTS:,} limit"
    return None


@dataclass
class AutoApproveOutcome:
    approved: int
    skipped: int
    errored: int


def auto_approve_pending_requests(
    *,
    max_requests: int,
    on_event: Callable[[str], None] | None = None,
) -> AutoApproveOutcome:
    """Refresh stats on pending auto-approve candidates and approve the ones that qualify.

    Candidates are pending event removals whose submitter didn't opt out. Each one's ClickHouse stats
    are refreshed first, so the size decision is made against a count measured moments earlier rather
    than whatever a person fetched at some unknown past time.

    A failure on one request is reported and skipped rather than raised: one unparseable predicate or
    timed-out count must not stop the other candidates in the same sweep. ``on_event`` receives a
    human-readable line per request for the caller to log.
    """
    log = on_event or (lambda _message: None)
    # Least-recently-measured first, never-measured before that. A request the sweep can't approve —
    # over the limit, range still open, predicate that won't compile — stays pending and stays a
    # candidate forever, so ordering by age would park it at the front of every tick and starve the
    # requests behind it. Ordering by the measurement instead means taking a slot costs you your place.
    candidates = DataDeletionRequest.objects.filter(
        status=RequestStatus.PENDING,
        request_type=RequestType.EVENT_REMOVAL,
        requires_approval=False,
    ).order_by(F("stats_calculated_at").asc(nulls_first=True), "created_at")[:max_requests]

    approved = skipped = errored = 0
    for request in candidates:
        try:
            refresh_deletion_stats(request)
        except Exception as exc:
            errored += 1
            log(f"Request {request.pk}: could not refresh stats, leaving pending: {exc}")
            continue

        blocker = auto_approve_blocker(request)
        if blocker is not None:
            skipped += 1
            log(f"Request {request.pk}: left pending for review because {blocker}.")
            continue

        # Guarded on the same conditions that selected the request. A concurrent criteria edit resets
        # it to DRAFT and clears its stats, so this is what stops the sweep approving criteria whose
        # count no longer describes them.
        updated = DataDeletionRequest.objects.filter(
            pk=request.pk,
            status=RequestStatus.PENDING,
            requires_approval=False,
        ).update(
            status=RequestStatus.APPROVED,
            approved=True,
            approved_automatically=True,
            approved_at=timezone.now(),
            execution_mode=ExecutionMode.DEFERRED,
            updated_at=timezone.now(),
        )
        if not updated:
            skipped += 1
            log(f"Request {request.pk}: changed while being evaluated, left alone.")
            continue
        approved += 1
        log(f"Request {request.pk}: auto-approved (deferred), {request.count:,} matching events.")

    return AutoApproveOutcome(approved=approved, skipped=skipped, errored=errored)
