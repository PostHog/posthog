import time
from typing import Any, Optional

from google.api_core.exceptions import GoogleAPIError
from google.cloud import bigquery
from google.cloud.bigquery.job import QueryJobConfig
from google.oauth2 import service_account
import structlog

from posthog.warehouse.connectors.base import (
    BaseWarehouseConnector,
    ColumnSchema,
    PushDownCapabilities,
    QueryCost,
    QueryResult,
    TableSchema,
)

logger = structlog.get_logger(__name__)


class BigQueryConnector(BaseWarehouseConnector):
    """Google BigQuery connector for direct querying"""

    def __init__(self, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(credentials, config)

        service_account_info = credentials.get("service_account_json")
        if not service_account_info:
            raise ValueError("BigQuery credentials must include 'service_account_json'")

        self.project_id = (
            credentials.get("project_id") or service_account_info.get("project_id")
        )
        if not self.project_id:
            raise ValueError("BigQuery credentials must include 'project_id'")

        self.default_dataset = credentials.get("default_dataset")

        try:
            self.credentials_obj = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=[
                    "https://www.googleapis.com/auth/bigquery",
                    "https://www.googleapis.com/auth/cloud-platform",
                ],
            )
            self.client = bigquery.Client(
                credentials=self.credentials_obj,
                project=self.project_id,
            )
        except Exception as e:
            logger.error(f"Failed to initialize BigQuery client: {e}")
            raise ValueError(f"Invalid BigQuery credentials: {e}")

    def execute_query(
        self, sql: str, params: Optional[dict[str, Any]] = None
    ) -> QueryResult:
        """Execute SQL query on BigQuery"""
        job_config = QueryJobConfig(
            use_query_cache=True,
            timeout_ms=self.get_timeout() * 1000,
        )

        start_time = time.time()

        try:
            query_job = self.client.query(sql, job_config=job_config)
            result = query_job.result()

            execution_time_ms = int((time.time() - start_time) * 1000)

            rows = [dict(row) for row in result]
            columns = [field.name for field in result.schema]

            bytes_processed = query_job.total_bytes_processed or 0
            cached = query_job.cache_hit or False

            logger.info(
                f"BigQuery query executed successfully",
                execution_time_ms=execution_time_ms,
                bytes_processed=bytes_processed,
                cached=cached,
                row_count=len(rows),
            )

            return QueryResult(
                rows=rows,
                columns=columns,
                execution_time_ms=execution_time_ms,
                bytes_processed=bytes_processed,
                cached=cached,
            )

        except GoogleAPIError as e:
            logger.error(f"BigQuery query failed: {e}")
            raise Exception(f"BigQuery query failed: {e}")

    def get_schema(self, schema_name: Optional[str] = None) -> list[TableSchema]:
        """Retrieve available tables and columns from BigQuery dataset"""
        dataset_id = schema_name or self.default_dataset

        if not dataset_id:
            raise ValueError(
                "Dataset ID must be provided either in schema_name parameter or as default_dataset in credentials"
            )

        try:
            dataset_ref = self.client.dataset(dataset_id, project=self.project_id)
            tables = list(self.client.list_tables(dataset_ref))

            schemas: list[TableSchema] = []

            for table_item in tables:
                table_ref = dataset_ref.table(table_item.table_id)
                table = self.client.get_table(table_ref)

                columns = [
                    ColumnSchema(
                        name=field.name,
                        type=field.field_type,
                        nullable=field.mode == "NULLABLE",
                    )
                    for field in table.schema
                ]

                schemas.append(
                    TableSchema(
                        name=f"{dataset_id}.{table.table_id}",
                        columns=columns,
                        row_count=table.num_rows,
                        size_bytes=table.num_bytes,
                    )
                )

            logger.info(
                f"Retrieved schema for BigQuery dataset",
                dataset_id=dataset_id,
                table_count=len(schemas),
            )

            return schemas

        except GoogleAPIError as e:
            logger.error(f"Failed to get BigQuery schema: {e}")
            raise Exception(f"Failed to get BigQuery schema: {e}")

    def estimate_cost(self, sql: str) -> QueryCost:
        """Estimate query cost using BigQuery dry run"""
        try:
            job_config = QueryJobConfig(dry_run=True, use_query_cache=False)
            query_job = self.client.query(sql, job_config=job_config)

            bytes_scanned = query_job.total_bytes_processed or 0

            # BigQuery on-demand pricing: $6.25 per TB (as of 2024)
            # https://cloud.google.com/bigquery/pricing#on_demand_pricing
            cost_per_tb = 6.25
            cost_usd = (bytes_scanned / 1_000_000_000_000) * cost_per_tb

            warning = None
            if cost_usd > 1.0:
                warning = f"This query will scan {bytes_scanned / 1e9:.2f} GB and cost approximately ${cost_usd:.2f}"
            elif cost_usd > 0.1:
                warning = f"This query will scan {bytes_scanned / 1e9:.2f} GB (estimated cost: ${cost_usd:.2f})"

            logger.info(
                f"BigQuery cost estimate",
                bytes_scanned=bytes_scanned,
                cost_usd=cost_usd,
            )

            return QueryCost(
                estimated_bytes=bytes_scanned,
                estimated_cost_usd=cost_usd,
                warning_message=warning,
            )

        except GoogleAPIError as e:
            logger.error(f"Failed to estimate BigQuery cost: {e}")
            return QueryCost(
                estimated_bytes=0,
                estimated_cost_usd=0.0,
                warning_message=f"Could not estimate cost: {e}",
            )

    def test_connection(self) -> bool:
        """Test if BigQuery connection credentials are valid"""
        try:
            query = "SELECT 1 as test"
            job_config = QueryJobConfig(
                use_query_cache=True,
                timeout_ms=5000,
            )
            query_job = self.client.query(query, job_config=job_config)
            result = query_job.result()

            list(result)

            logger.info("BigQuery connection test successful")
            return True

        except Exception as e:
            logger.error(f"BigQuery connection test failed: {e}")
            return False

    def supports_push_down(self) -> PushDownCapabilities:
        """BigQuery supports most push-down optimizations"""
        return PushDownCapabilities(
            supports_predicate=True,
            supports_projection=True,
            supports_aggregation=True,
            supports_limit=True,
            supports_join=True,
        )

    def close(self) -> None:
        """Close BigQuery client connection"""
        if hasattr(self, "client"):
            self.client.close()
            logger.info("BigQuery client closed")
