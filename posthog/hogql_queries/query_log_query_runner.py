from posthog.schema import CachedHogQLQueryResponse, HogQLQuery, HogQLQueryResponse

from posthog.hogql import ast

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models import Team


class QueryLogQueryRunner(QueryRunner[HogQLQuery, HogQLQueryResponse, CachedHogQLQueryResponse]):
    query: HogQLQuery
    response: HogQLQueryResponse
    cached_response: CachedHogQLQueryResponse

    def __init__(self, query_id: str, team: Team, **kwargs):
        self.query_id_param = query_id
        # Create a dummy HogQLQuery for interface compatibility
        dummy_query = HogQLQuery(kind="HogQLQuery", query="SELECT 1")
        super().__init__(dummy_query, team, **kwargs)

    def _calculate(self) -> HogQLQueryResponse:
        # Raw ClickHouse query to query_log_archive table
        raw_query = """
        SELECT
            query_id,
            lc_id as endpoint,
            lc_query__query as query,
            query_start_time,
            query_duration_ms,
            lc_name as hogql_name,
            lc_user_id as created_by,
            read_rows,
            read_bytes,
            result_rows,
            result_bytes,
            memory_usage,
            type as status,
            exception_code,
            lc_access_method = 'personal_api_key' as is_personal_api_key_request,
            lc_api_key_label as api_key_label,
            lc_api_key_mask as api_key_mask,
            ProfileEvents_OSCPUVirtualTimeMicroseconds as cpu_microseconds,
            ProfileEvents_RealTimeMicroseconds as real_time_microseconds,
            ProfileEvents_S3ListObjects as s3_list_objects,
            ProfileEvents_S3HeadObject as s3_head_object,
            ProfileEvents_S3GetObjectAttributes as s3_get_object_attributes,
            ProfileEvents_S3GetObject as s3_get_object,
            ProfileEvents_ReadBufferFromS3Bytes as read_buffer_from_s3_bytes,
            event_time,
            event_date
        FROM query_log_archive
        WHERE team_id = %(team_id)s
            AND lc_client_query_id = %(query_id)s
            AND event_date > today() - interval 7 days
        ORDER BY query_start_time DESC
        LIMIT 100
        """

        # Execute the raw ClickHouse query
        results = sync_execute(
            raw_query, {"team_id": self.team.pk, "query_id": self.query_id_param}, workload=self.workload
        )

        # Convert results to the expected format
        columns = [
            "query_id",
            "endpoint",
            "query",
            "query_start_time",
            "query_duration_ms",
            "hogql_name",
            "created_by",
            "read_rows",
            "read_bytes",
            "result_rows",
            "result_bytes",
            "memory_usage",
            "status",
            "exception_code",
            "is_personal_api_key_request",
            "api_key_label",
            "api_key_mask",
            "cpu_microseconds",
            "real_time_microseconds",
            "s3_list_objects",
            "s3_head_object",
            "s3_get_object_attributes",
            "s3_get_object",
            "read_buffer_from_s3_bytes",
            "event_time",
            "event_date",
        ]

        return HogQLQueryResponse(
            results=results,
            columns=columns,
            types=[
                ("query_id", "String"),
                ("endpoint", "String"),
                ("query", "String"),
                ("query_start_time", "DateTime"),
                ("query_duration_ms", "UInt64"),
                ("hogql_name", "String"),
                ("created_by", "UInt64"),
                ("read_rows", "UInt64"),
                ("read_bytes", "UInt64"),
                ("result_rows", "UInt64"),
                ("result_bytes", "UInt64"),
                ("memory_usage", "UInt64"),
                ("status", "String"),
                ("exception_code", "UInt32"),
                ("is_personal_api_key_request", "UInt8"),
                ("api_key_label", "String"),
                ("api_key_mask", "String"),
                ("cpu_microseconds", "UInt64"),
                ("real_time_microseconds", "UInt64"),
                ("s3_list_objects", "UInt64"),
                ("s3_head_object", "UInt64"),
                ("s3_get_object_attributes", "UInt64"),
                ("s3_get_object", "UInt64"),
                ("read_buffer_from_s3_bytes", "UInt64"),
                ("event_time", "DateTime"),
                ("event_date", "Date"),
            ],
        )

    def to_query(self) -> ast.SelectQuery:
        # Return a dummy query since we're using raw ClickHouse
        return ast.SelectQuery(
            select=[ast.Constant(value=1)], select_from=ast.JoinExpr(table=ast.Field(chain=["query_log_archive"]))
        )
