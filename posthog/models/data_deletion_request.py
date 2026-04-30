from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel


def jsonhas_expr(prop: str, param_prefix: str) -> str:
    """Build a ClickHouse ``JSONHas`` expression for a (possibly nested) property path.

    Splits dotted names so ``"sub.prop"`` becomes
    ``JSONHas(properties, %(prefix_0)s, %(prefix_1)s)``.
    """
    parts = prop.split(".")
    args = ", ".join(f"%({param_prefix}_{i})s" for i in range(len(parts)))
    return f"JSONHas(properties, {args})"


def compile_hogql_predicate(obj) -> tuple[str, dict]:
    """Parse and compile ``obj.hogql_predicate`` into a ClickHouse SQL fragment.

    Returns ``(sql_fragment, extra_params)``. Both are empty when the predicate
    is blank. The fragment excludes the surrounding parentheses so callers can
    decide how to splice it (typically ``AND (<fragment>)``). Raises
    :class:`~django.core.exceptions.ValidationError` on parse, resolution or
    subquery errors — suitable for use inside ``Model.clean()``.
    """
    predicate = (getattr(obj, "hogql_predicate", "") or "").strip()
    if not predicate:
        return "", {}

    # Imported lazily: HogQL pulls in the full schema graph, which we don't want
    # to load for every model import (admin registration, migrations, etc.).
    from posthog.hogql import ast
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.hogql import translate_hogql
    from posthog.hogql.parser import parse_expr
    from posthog.hogql.visitor import TraversingVisitor

    class _RejectSubqueries(TraversingVisitor):
        def visit_select_query(self, node: ast.SelectQuery) -> None:
            raise ValidationError({"hogql_predicate": "Subqueries are not allowed in a data deletion predicate."})

        def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
            raise ValidationError({"hogql_predicate": "Subqueries are not allowed in a data deletion predicate."})

    try:
        parsed = parse_expr(predicate)
    except Exception as exc:
        raise ValidationError({"hogql_predicate": f"Could not parse HogQL: {exc}"}) from exc

    _RejectSubqueries().visit(parsed)

    if obj.team_id is None:
        raise ValidationError({"hogql_predicate": "team_id must be set before validating the predicate."})

    context = HogQLContext(team_id=obj.team_id, within_non_hogql_query=True, enable_select_queries=True)
    try:
        sql = translate_hogql(predicate, context, dialect="clickhouse")
    except Exception as exc:
        raise ValidationError({"hogql_predicate": f"Could not compile HogQL: {exc}"}) from exc

    return sql, dict(context.values)


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
        help_text="Opt in to deleting every event for the team in the given time range. "
        "Only honored for event_removal requests. Requires events to be empty.",
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
        help_text="Property names to remove. Required for property_removal requests.",
    )
    person_uuids = ArrayField(
        models.UUIDField(),
        blank=True,
        default=list,
        help_text="Person UUIDs to target. Combined with person_distinct_ids; total ≤ 1000.",
    )
    person_distinct_ids = ArrayField(
        models.CharField(max_length=400),
        blank=True,
        default=list,
        help_text="Person distinct IDs to target. Combined with person_uuids; total ≤ 1000.",
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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"DataDeletionRequest({self.request_type}, team={self.team_id}, status={self.status})"

    def clean(self) -> None:
        super().clean()
        if self.request_type == RequestType.EVENT_REMOVAL:
            self._clean_event_removal()
        elif self.request_type == RequestType.PROPERTY_REMOVAL:
            self._clean_property_removal()
        elif self.request_type == RequestType.PERSON_REMOVAL:
            self._clean_person_removal()
            return  # PERSON_REMOVAL never has hogql_predicate / events / properties
        else:
            raise ValidationError({"request_type": f"Unknown request_type: {self.request_type}"})

        if self.delete_all_events and self.request_type != RequestType.EVENT_REMOVAL:
            raise ValidationError(
                {"delete_all_events": "delete_all_events is only valid for event_removal requests."},
            )
        if self.hogql_predicate:
            compile_hogql_predicate(self)

    def _clean_event_removal(self) -> None:
        self._require_time_range()
        if self.delete_all_events and self.events:
            raise ValidationError({"events": "Events must be empty when delete_all_events is set."})
        if not self.delete_all_events and not self.events:
            raise ValidationError(
                {"events": "Provide at least one event, or set delete_all_events to delete every event."}
            )
        self._reject_person_fields()

    def _clean_property_removal(self) -> None:
        self._require_time_range()
        self._reject_person_fields()

    def _require_time_range(self) -> None:
        if self.start_time is None or self.end_time is None:
            raise ValidationError({"start_time": "start_time and end_time are required for event/property removal."})
        if self.start_time >= self.end_time:
            raise ValidationError({"start_time": "start_time must be before end_time."})

    def _clean_person_removal(self) -> None:
        total = len(self.person_uuids) + len(self.person_distinct_ids)
        if total == 0:
            raise ValidationError({"person_uuids": "Provide at least one person_uuid or person_distinct_id."})
        if total > 1000:
            raise ValidationError({"person_uuids": "Combined person_uuids + person_distinct_ids must be ≤ 1000."})
        if not (self.person_drop_profiles or self.person_drop_events or self.person_drop_recordings):
            raise ValidationError(
                {"person_drop_profiles": "At least one of person_drop_profiles / events / recordings must be true."}
            )
        if self.events or self.delete_all_events:
            raise ValidationError({"events": "events / delete_all_events are not valid for person_removal."})
        if self.properties:
            raise ValidationError({"properties": "properties are not valid for person_removal."})
        if self.hogql_predicate:
            raise ValidationError({"hogql_predicate": "hogql_predicate is not valid for person_removal."})

    def _reject_person_fields(self) -> None:
        if self.person_uuids or self.person_distinct_ids:
            raise ValidationError(
                {"person_uuids": "person_uuids / person_distinct_ids are only valid for person_removal."}
            )
        if self.person_drop_profiles or self.person_drop_events or self.person_drop_recordings:
            raise ValidationError({"person_drop_profiles": "person_drop_* flags are only valid for person_removal."})
