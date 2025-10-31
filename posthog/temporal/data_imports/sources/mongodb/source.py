from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import MongoDBSourceConfig
from posthog.temporal.data_imports.sources.mongodb.mongo import (
    _parse_connection_string,
    filter_mongo_incremental_fields,
    get_schemas as get_mongo_schemas,
    mongo_source,
)
from posthog.warehouse.types import ExternalDataSourceType


@SourceRegistry.register
class MongoDBSource(BaseSource[MongoDBSourceConfig], ValidateDatabaseHostMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONGODB

    def get_schemas(self, config: MongoDBSourceConfig, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        mongo_schemas = get_mongo_schemas(config)

        filtered_results = [
            (collection_name, filter_mongo_incremental_fields(columns, config.connection_string, collection_name))
            for collection_name, columns in mongo_schemas.items()
        ]

        return [
            SourceSchema(
                name=name,
                supports_incremental=len(incremental_fields) > 0,
                supports_append=len(incremental_fields) > 0,
                incremental_fields=[
                    {
                        "label": field_name,
                        "type": field_type,
                        "field": field_name,
                        "field_type": field_type,
                    }
                    for field_name, field_type in incremental_fields
                ],
            )
            for name, incremental_fields in filtered_results
        ]

    def validate_credentials(self, config: MongoDBSourceConfig, team_id: int) -> tuple[bool, str | None]:
        from pymongo.errors import OperationFailure

        try:
            connection_params = _parse_connection_string(config.connection_string)
        except:
            return False, "Invalid connection string"

        if not connection_params.get("database"):
            return False, "Database name is required in connection string"

        if not connection_params.get("is_srv"):
            valid_host, host_errors = self.is_database_host_valid(connection_params["host"], team_id, False)
            if not valid_host:
                return False, host_errors

        try:
            schemas = self.get_schemas(config, team_id)
            if len(schemas) == 0:
                return False, "No collections found in database"
        except OperationFailure as e:
            capture_exception(e)
            return False, "MongoDB authentication failed"
        except Exception as e:
            capture_exception(e)
            return False, "Failed to connect to MongoDB database"

        return True, None

    def source_for_pipeline(self, config: MongoDBSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return mongo_source(
            connection_string=config.connection_string,
            collection_name=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            logger=inputs.logger,
            incremental_field=inputs.incremental_field,
            incremental_field_type=inputs.incremental_field_type,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MONGO_DB,
            label="MongoDB",
            caption="Enter your MongoDB connection string to automatically pull your MongoDB data into the PostHog Data warehouse.",
            betaSource=True,
            iconPath="/static/services/Mongodb.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/mongodb",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="connection_string",
                        label="Connection String",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mongodb://username:password@host:port/database?authSource=admin",
                    )
                ],
            ),
        )
