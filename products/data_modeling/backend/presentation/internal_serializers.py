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
        "More than one entry means duplicate backing tables."
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
