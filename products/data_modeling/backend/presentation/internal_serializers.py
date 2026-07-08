"""Read-only serializers for the data_modeling_ops internal API.

These back service-to-service responses consumed by the modeling-ops admin app; they
intentionally expose operational fields (engine, storage deltas, full errors) that the
customer-facing serializers hide.
"""

from rest_framework import serializers

from products.data_modeling.backend.facade.models import DAG, DataModelingJob, DataWarehouseSavedQuery, Edge, Node
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class InternalBackingTableSerializer(serializers.ModelSerializer):
    is_linked = serializers.SerializerMethodField(
        help_text="Whether this table is the one the saved query's table FK currently points at. "
        "Unlinked rows with the same name are orphaned duplicate backing tables."
    )

    class Meta:
        model = DataWarehouseTable
        fields = [
            "id",
            "name",
            "format",
            "url_pattern",
            "queryable_folder",
            "row_count",
            "size_in_s3_mib",
            "created_at",
            "is_linked",
        ]
        read_only_fields = fields

    def get_is_linked(self, table: DataWarehouseTable) -> bool:
        return str(table.id) == str(self.context.get("linked_table_id"))


class InternalSavedQuerySummarySerializer(serializers.ModelSerializer):
    table_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Backing DataWarehouseTable id, when materialized."
    )

    class Meta:
        model = DataWarehouseSavedQuery
        fields = [
            "id",
            "name",
            "status",
            "last_run_at",
            "latest_error",
            "is_materialized",
            "sync_frequency_interval",
            "origin",
            "table_id",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "latest_error": {"help_text": "Full latest error text, untruncated."},
            "sync_frequency_interval": {
                "help_text": "v1 per-query materialization cadence; null once a team is on v2 DAG scheduling."
            },
        }


class InternalSavedQueryNodeContextSerializer(serializers.Serializer):
    node_id = serializers.UUIDField(help_text="Node id representing this saved query in a DAG.")
    dag_id = serializers.UUIDField(help_text="DAG the node belongs to.")
    dag_name = serializers.CharField(help_text="Name of the DAG the node belongs to.")
    node_type = serializers.CharField(help_text="Node type: table, view, matview, or endpoint.")
    upstream = serializers.ListField(
        child=serializers.CharField(), help_text="Names of immediate upstream nodes in this DAG."
    )
    downstream = serializers.ListField(
        child=serializers.CharField(), help_text="Names of immediate downstream nodes in this DAG."
    )


class InternalScheduleRecentActionSerializer(serializers.Serializer):
    scheduled_at = serializers.CharField(allow_null=True, help_text="When the action was scheduled to run (ISO).")
    started_at = serializers.CharField(allow_null=True, help_text="When the action actually started (ISO).")
    workflow_id = serializers.CharField(allow_null=True, help_text="Workflow id the action started.")
    workflow_run_id = serializers.CharField(
        allow_null=True, help_text="First execution run id of the started workflow."
    )


class InternalScheduleInfoSerializer(serializers.Serializer):
    schedule_id = serializers.CharField(help_text="Temporal schedule id (saved query id for v1, DAG id for v2).")
    exists = serializers.BooleanField(help_text="Whether the schedule exists in Temporal.")
    workflow_name = serializers.CharField(
        allow_null=True, help_text="Workflow the schedule starts — the authoritative v1/v2 discriminator."
    )
    kind = serializers.ChoiceField(
        choices=["v1_saved_query", "v2_dag", "other"],
        help_text="Classification by workflow name: data-modeling-run = v1, data-modeling-execute-dag = v2.",
    )
    paused = serializers.BooleanField(allow_null=True, help_text="Whether the schedule is paused.")
    note = serializers.CharField(allow_null=True, help_text="Operator note on the schedule state, if any.")
    next_run_at = serializers.CharField(allow_null=True, help_text="Next scheduled action time (ISO), if any.")
    spec = serializers.JSONField(help_text="Spec summary: intervals, cron expressions, calendar count, jitter, tz.")
    recent_actions = InternalScheduleRecentActionSerializer(
        many=True, help_text="Up to 5 most recent schedule actions with started workflow ids."
    )
    search_attributes = serializers.JSONField(
        help_text="Temporal search attributes on the schedule (PostHogTeamId, PostHogDagId, PostHogScheduleType...). "
        "Informational only — never used for classification."
    )


class InternalEntityScheduleSerializer(serializers.Serializer):
    entity_type = serializers.ChoiceField(
        choices=["dag", "saved_query"], help_text="Kind of entity this schedule slot belongs to."
    )
    entity_id = serializers.CharField(help_text="DAG or saved query id — also the expected Temporal schedule id.")
    entity_name = serializers.CharField(help_text="Name of the DAG or saved query.")
    schedule = InternalScheduleInfoSerializer(
        allow_null=True,
        help_text="Live Temporal schedule state, or null when no schedule exists for this entity — "
        "a materialized entity with null here is unscheduled.",
    )


class InternalSavedQueryDetailSerializer(InternalSavedQuerySummarySerializer):
    query = serializers.JSONField(read_only=True, help_text="Stored HogQL query payload (JSON with a 'query' key).")
    columns = serializers.JSONField(
        read_only=True, allow_null=True, help_text="Dict of all columns with ClickHouse type."
    )
    created_by_email = serializers.SerializerMethodField(help_text="Email of the user who created the saved query.")
    last_successful_job_at = serializers.SerializerMethodField(
        help_text="Completion time of the most recent COMPLETED materialization job. More trustworthy than "
        "last_run_at, which the v2 DAG success path does not write."
    )
    nodes = serializers.SerializerMethodField(
        help_text="DAG context: one entry per DAG this saved query has a node in, with immediate lineage."
    )
    double_materialized = serializers.SerializerMethodField(
        help_text="True when the saved query has nodes in more than one DAG (duplicate materialization)."
    )
    backing_tables = serializers.SerializerMethodField(
        help_text="All DataWarehouseTable rows sharing this saved query's name, linked or not. "
        "More than one entry means duplicate backing tables — treat as a lead, not proof: the match "
        "is by name, so an unrelated table of the same name also shows up here."
    )
    schedule_truth = serializers.SerializerMethodField(
        help_text="Live Temporal coverage: covered_by (v1/v2/none), the v1 per-query schedule, and per-DAG "
        "v2 schedules. Degrades to {'error': ...} when Temporal is unreachable."
    )

    class Meta(InternalSavedQuerySummarySerializer.Meta):
        fields = [
            *InternalSavedQuerySummarySerializer.Meta.fields,
            "query",
            "columns",
            "created_by_email",
            "last_successful_job_at",
            "nodes",
            "double_materialized",
            "backing_tables",
            "schedule_truth",
        ]
        read_only_fields = fields

    def get_created_by_email(self, saved_query: DataWarehouseSavedQuery) -> str | None:
        return saved_query.created_by.email if saved_query.created_by else None

    def get_last_successful_job_at(self, saved_query: DataWarehouseSavedQuery) -> str | None:
        last_successful_job_at = self.context.get("last_successful_job_at")
        return last_successful_job_at.isoformat() if last_successful_job_at else None

    def get_nodes(self, saved_query: DataWarehouseSavedQuery) -> list[dict]:
        return list(InternalSavedQueryNodeContextSerializer(self.context.get("nodes", []), many=True).data)

    def get_double_materialized(self, saved_query: DataWarehouseSavedQuery) -> bool:
        return len(self.context.get("nodes", [])) > 1

    def get_backing_tables(self, saved_query: DataWarehouseSavedQuery) -> list[dict]:
        return list(
            InternalBackingTableSerializer(self.context.get("backing_tables", []), many=True, context=self.context).data
        )

    def get_schedule_truth(self, saved_query: DataWarehouseSavedQuery) -> dict:
        return self.context.get("schedule_truth") or {}


class InternalDataModelingJobSerializer(serializers.ModelSerializer):
    saved_query_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Saved query this job materialized."
    )

    class Meta:
        model = DataModelingJob
        fields = [
            "id",
            "saved_query_id",
            "status",
            "engine",
            "rows_materialized",
            "rows_expected",
            "error",
            "workflow_id",
            "workflow_run_id",
            "parent_workflow_id",
            "storage_delta_mib",
            "created_at",
            "updated_at",
            "last_run_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "engine": {"help_text": "Materialization engine: clickhouse or duckgres."},
            "error": {"help_text": "Full error text, untruncated."},
            "storage_delta_mib": {"help_text": "Storage growth caused by this job, in MiB."},
        }


class InternalDAGSummarySerializer(serializers.ModelSerializer):
    node_count = serializers.IntegerField(read_only=True, default=0, help_text="Number of nodes in the DAG.")

    class Meta:
        model = DAG
        fields = [
            "id",
            "name",
            "sync_frequency_interval",
            "node_count",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "sync_frequency_interval": {"help_text": "DAG-level materialization cadence for v2 scheduling."},
        }


class InternalNodeSerializer(serializers.ModelSerializer):
    saved_query_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Saved query backing this node; null for source tables."
    )
    last_run_at = serializers.SerializerMethodField(
        help_text="Last run time recorded in node system properties, if any."
    )
    last_run_status = serializers.SerializerMethodField(
        help_text="Last run status recorded in node system properties, if any."
    )

    class Meta:
        model = Node
        fields = [
            "id",
            "name",
            "type",
            "saved_query_id",
            "last_run_at",
            "last_run_status",
        ]
        read_only_fields = fields

    def get_last_run_at(self, node: Node) -> str | None:
        return (node.properties or {}).get("system", {}).get("last_run_at")

    def get_last_run_status(self, node: Node) -> str | None:
        return (node.properties or {}).get("system", {}).get("last_run_status")


class InternalEdgeSerializer(serializers.ModelSerializer):
    source_id = serializers.UUIDField(read_only=True, help_text="Upstream node id.")
    target_id = serializers.UUIDField(read_only=True, help_text="Downstream node id.")

    class Meta:
        model = Edge
        fields = ["id", "source_id", "target_id"]
        read_only_fields = fields


class InternalFleetTeamSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team with data-modeling activity.")
    team_name = serializers.CharField(allow_null=True, help_text="Team name, null if the team row is gone.")
    organization_id = serializers.CharField(allow_null=True, help_text="Owning organization id.")
    saved_query_count = serializers.IntegerField(help_text="Non-deleted saved queries.")
    materialized_saved_query_count = serializers.IntegerField(help_text="Saved queries that are materialized.")
    failing_saved_query_count = serializers.IntegerField(help_text="Saved queries whose last run failed.")
    saved_queries_with_sync_frequency_count = serializers.IntegerField(
        help_text="Saved queries still carrying a v1 sync_frequency_interval (migration switch C not cleaned)."
    )
    endpoint_origin_saved_query_count = serializers.IntegerField(
        help_text="Saved queries created by endpoint materialization."
    )
    dag_count = serializers.IntegerField(help_text="Number of DAGs.")


class InternalMigrationMatrixRowSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team the switch states describe.")
    team_name = serializers.CharField(allow_null=True, help_text="Team name, null if the team row is gone.")
    switch_a_v2_flag_enabled = serializers.BooleanField(
        help_text="Flag data-modeling-backend-v2 for this team. The flag is an exclusion list: "
        "false means the team is excluded from the v2 backend."
    )
    switch_b_v2_schedule_present = serializers.BooleanField(
        allow_null=True,
        help_text="Whether any of the team's DAGs has a live v2 execute-dag Temporal schedule; "
        "null when Temporal was unreachable (see temporal_error).",
    )
    switch_c_sync_frequencies_remaining = serializers.IntegerField(
        help_text="Saved queries still carrying sync_frequency_interval — nonzero after a v2 "
        "migration means cleanup never finished."
    )
    dag_count = serializers.IntegerField(help_text="Number of DAGs.")
    classification = serializers.ChoiceField(
        choices=[
            "fully_v2",
            "v2_scheduled_flag_excluded",
            "v2_scheduled_cleanup_pending",
            "not_migrated",
            "v1_flag_excluded",
            "no_dags",
        ],
        allow_null=True,
        help_text="Derived label across the three switches; v2_scheduled_flag_excluded is the "
        "'Sync now' storm cohort (scheduled on v2 but excluded from the v2 flag). Null when "
        "Temporal was unreachable — switch B is unknown, so no label would be trustworthy.",
    )


class InternalOrphanedScheduleSerializer(serializers.Serializer):
    schedule_id = serializers.CharField(help_text="Temporal schedule id with no live owning entity.")
    workflow_name = serializers.CharField(allow_null=True, help_text="Workflow the schedule starts.")
    kind = serializers.ChoiceField(
        choices=["v1_saved_query", "v2_dag"],
        help_text="v1_saved_query: schedule id is a deleted saved query; v2_dag: a deleted DAG.",
    )
    paused = serializers.BooleanField(allow_null=True, help_text="Whether the schedule is paused.")
    note = serializers.CharField(allow_null=True, help_text="Operator note on the schedule state, if any.")
    next_run_at = serializers.CharField(allow_null=True, help_text="Next scheduled action time (ISO), if any.")
    team_id = serializers.IntegerField(
        allow_null=True,
        help_text="Team from the PostHogTeamId search attribute; null on schedules predating the backfill.",
    )


class InternalUnscheduledEntitySerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team owning the unscheduled entity.")
    saved_query_id = serializers.CharField(help_text="Materialized saved query with no covering schedule.")
    name = serializers.CharField(help_text="Saved query name.")
    is_materialized = serializers.BooleanField(help_text="Always true today; kept for future entity kinds.")
    sync_frequency_interval = serializers.DurationField(
        allow_null=True, help_text="Residual v1 cadence, if any — a hint the v1 schedule went missing."
    )
    last_run_at = serializers.DateTimeField(allow_null=True, help_text="Last recorded run.")
    dag_ids = serializers.ListField(
        child=serializers.CharField(), help_text="DAGs this saved query has nodes in (none of them scheduled)."
    )


class InternalFailingSavedQuerySerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team owning the failing saved query.")
    saved_query_id = serializers.CharField(help_text="Failing saved query id.")
    name = serializers.CharField(help_text="Saved query name.")
    latest_error = serializers.CharField(allow_null=True, help_text="Full latest error text, untruncated.")
    last_run_at = serializers.DateTimeField(allow_null=True, help_text="Last recorded run.")
    last_failed_job_at = serializers.DateTimeField(
        allow_null=True, help_text="Creation time of the most recent FAILED job."
    )
    consecutive_failures_by_engine = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Consecutive FAILED jobs per engine, newest-first, streak broken by that engine's "
        "first non-failed job. Engine-split so duck-shadow jobs don't pollute the serving count.",
    )
    nodes = serializers.ListField(
        child=serializers.JSONField(),
        help_text="Node context: node_id, dag_id, and suspension state from node system properties "
        "(headroom for the per-node circuit breaker).",
    )


class InternalFailingScheduleGroupSerializer(serializers.Serializer):
    schedule_id = serializers.CharField(
        allow_null=True, help_text="Covering Temporal schedule id; null when nothing covers the entities."
    )
    schedule_kind = serializers.ChoiceField(
        choices=["v1_saved_query", "v2_dag", "none"],
        help_text="Classification of the covering schedule by workflow name.",
    )
    paused = serializers.BooleanField(allow_null=True, help_text="Whether the covering schedule is paused.")
    team_id = serializers.IntegerField(help_text="Team owning the affected entities.")
    affected_saved_queries = InternalFailingSavedQuerySerializer(
        many=True, help_text="Failing saved queries hanging off this schedule."
    )


class InternalMultiDagSavedQuerySerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team owning the saved query.")
    saved_query_id = serializers.CharField(help_text="Saved query with nodes in more than one DAG.")
    name = serializers.CharField(help_text="Saved query name.")
    is_materialized = serializers.BooleanField(help_text="Whether the saved query is materialized.")
    dags = serializers.ListField(
        child=serializers.JSONField(), help_text="The DAGs it appears in: dag_id + dag_name each."
    )


class InternalDuplicateBackingTableGroupSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team owning the saved query and tables.")
    saved_query_id = serializers.CharField(help_text="Saved query whose name matches multiple backing tables.")
    name = serializers.CharField(help_text="Shared saved query / table name.")
    linked_table_id = serializers.CharField(
        allow_null=True, help_text="Table the saved query's table FK points at; the others are orphans."
    )
    tables = serializers.SerializerMethodField(help_text="All same-named tables, oldest first, with is_linked.")

    def get_tables(self, group: dict) -> list[dict]:
        return list(
            InternalBackingTableSerializer(
                group["tables"], many=True, context={"linked_table_id": group["linked_table_id"]}
            ).data
        )


class InternalResolveMatchSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["saved_query", "endpoint", "dag", "node", "job"],
        help_text="Entity kind the match resolved to (schedule/workflow/name queries resolve to these).",
    )
    team_id = serializers.IntegerField(allow_null=True, help_text="Owning team.")
    id = serializers.CharField(help_text="Entity id.")
    name = serializers.CharField(allow_blank=True, help_text="Entity name, when it has one.")
    detail = serializers.JSONField(help_text="Kind-specific extras (status, dag_id, saved_query_id, ...).")


class InternalTeamOverviewSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team the overview describes.")
    v2_backend_enabled = serializers.BooleanField(
        help_text="Whether the data-modeling-backend-v2 flag is on for this team. The flag is an exclusion "
        "list, so false means the team is excluded from the v2 backend."
    )
    dag_count = serializers.IntegerField(help_text="Number of DAGs.")
    node_count = serializers.IntegerField(help_text="Number of nodes across all DAGs.")
    saved_query_count = serializers.IntegerField(help_text="Number of non-deleted saved queries.")
    materialized_saved_query_count = serializers.IntegerField(help_text="Saved queries that are materialized.")
    failing_saved_query_count = serializers.IntegerField(help_text="Saved queries whose last run failed.")
    saved_queries_with_sync_frequency_count = serializers.IntegerField(
        help_text="Saved queries still carrying a v1 sync_frequency_interval — nonzero on a v2 team means "
        "the v1-to-v2 migration never finished cleanup."
    )
    endpoint_origin_saved_query_count = serializers.IntegerField(
        help_text="Saved queries created by endpoint materialization."
    )
