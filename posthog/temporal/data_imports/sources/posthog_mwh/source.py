from __future__ import annotations

from typing import Optional, cast

import psycopg

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
)

from posthog.ducklake.client import make_duckgres_conninfo
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import PostHogMWHSourceConfig
from posthog.temporal.data_imports.sources.posthog_mwh.posthog_mwh import get_mwh_columns, get_mwh_tables

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PostHogMWHSource(SimpleSource[PostHogMWHSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTHOGMWH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POST_HOG_MWH,
            label="PostHog Managed Warehouse",
            caption="PostHog Warehouse Sources",
            iconPath="/static/services/posthog_mwh.png",
            fields=cast(list[FieldType], []),
            featureFlag="provision-managed-warehouse-beta",
            releaseStatus=ReleaseStatus.BETA,
        )

    def get_schemas(
        self,
        config: PostHogMWHSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        tables = get_mwh_tables(team_id)

        schemas: list[SourceSchema] = []
        for table in tables:
            qualified_name = f"{table['schema']}.{table['table']}"
            if names and qualified_name not in names:
                continue

            columns = get_mwh_columns(team_id, table["schema"], table["table"])

            schemas.append(
                SourceSchema(
                    name=qualified_name,
                    supports_incremental=False,
                    supports_append=False,
                    columns=columns,
                    source_schema=table["schema"],
                    source_table_name=table["table"],
                )
            )

        return schemas

    def validate_credentials(
        self, config: PostHogMWHSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            conninfo = make_duckgres_conninfo(team_id)
            with psycopg.connect(conninfo, connect_timeout=10) as conn:
                conn.execute("SELECT 1")
            return True, None
        except Exception as e:
            return False, f"Could not connect to managed warehouse: {e}"

    def source_for_pipeline(self, config: PostHogMWHSourceConfig, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError(
            "PostHogMWH uses server-side COPY TO S3 — import is handled directly in import_data_activity_sync"
        )
