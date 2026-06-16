from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from posthog.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import MongoDBSourceConfig
from posthog.temporal.data_imports.sources.mongodb.mongo import (
    DATABASE_NAME_REQUIRED_ERROR,
    _parse_connection_string,
    filter_mongo_incremental_fields,
    get_collection_names,
    get_leading_index_keys,
    get_schemas as get_mongo_schemas,
    mongo_client,
    mongo_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType

_MONGO_UNREACHABLE_MESSAGE = (
    "Could not reach your MongoDB cluster. Check that the cluster is running and that PostHog's "
    "IP addresses are allowlisted in your database's network access settings."
)


@SourceRegistry.register
class MongoDBSource(SimpleSource[MongoDBSourceConfig], ValidateDatabaseHostMixin):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONGODB

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        auth_failed_msg = "MongoDB authentication failed. Please check the username and password for this source."
        unescaped_credentials_msg = (
            "The username or password in your MongoDB connection string contains reserved characters "
            "(such as @, :, /, or %) that must be percent-encoded. URL-encode them with "
            "urllib.parse.quote_plus and update the connection string for this source."
        )
        return {
            "The DNS query name does not exist": None,
            # pymongo raises OperationFailure with codeName 'AuthenticationFailed' (code 18) and
            # errmsg 'Authentication failed.' when the credentials are wrong. Non-retryable error
            # matching is case-sensitive, so the previous lowercase "authentication failed" never
            # matched the real message — key off the stable codeName and the capitalised message.
            "AuthenticationFailed": auth_failed_msg,
            "Authentication failed": auth_failed_msg,
            "SSL handshake failed": None,
            # pymongo raises ServerSelectionTimeoutError when it can't select a usable cluster node
            # for the whole selection timeout. The reason varies — "No servers found yet" / "No
            # replica set members found yet" when nothing was ever discovered, or a per-server
            # "<host>: connection closed ... error=AutoReconnect(...)" when a host resolves but every
            # connection attempt is dropped for the entire window. All of these carry the
            # "Topology Description:" suffix that only ServerSelectionTimeoutError emits, so we key
            # off that single marker. On a managed cluster this is a persistent connectivity problem
            # — the worker IP isn't allowlisted, the cluster is paused/decommissioned, or the
            # connection string points at an endpoint the driver can't speak to — not a momentary
            # blip, so retrying the job won't recover it. A transient mid-sync drop surfaces
            # differently (a bare AutoReconnect / NetworkTimeout with no topology description) and
            # stays retryable.
            "Topology Description:": _MONGO_UNREACHABLE_MESSAGE,
            # pymongo raises InvalidURI ("Username and password must be escaped according to RFC
            # 3986, use urllib.parse.quote_plus") — and a ValueError with the same "must be escaped
            # according to RFC 3986" hint — when the stored connection string has unescaped reserved
            # characters in the credentials. The string itself is malformed, so every retry parses it
            # the same way and fails identically; only the user fixing the connection string recovers it.
            "must be escaped according to RFC 3986": unescaped_credentials_msg,
        }

    def get_schemas(
        self,
        config: MongoDBSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        mongo_schemas = get_mongo_schemas(config, team_id=team_id, names=names)

        connection_params = _parse_connection_string(config.connection_string, config.database_name)
        leading_keys_by_collection: dict[str, set[str] | None] = {}
        with mongo_client(config.connection_string, team_id=team_id) as client:
            db = client[connection_params["database"]]
            filtered_results = [
                (collection_name, filter_mongo_incremental_fields(columns, db[collection_name]))
                for collection_name, columns in mongo_schemas.items()
            ]
            for collection_name in mongo_schemas:
                leading_keys_by_collection[collection_name] = get_leading_index_keys(db[collection_name])

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
                        "is_indexed": (
                            True
                            if leading_keys_by_collection.get(name) is None
                            else field_name in (leading_keys_by_collection.get(name) or set())
                        ),
                    }
                    for field_name, field_type in incremental_fields
                ],
            )
            for name, incremental_fields in filtered_results
        ]

    def validate_credentials(
        self, config: MongoDBSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        from pymongo.errors import OperationFailure

        try:
            connection_params = _parse_connection_string(config.connection_string, config.database_name)
        except:
            return False, "Invalid connection string"

        if not connection_params.get("database"):
            return False, DATABASE_NAME_REQUIRED_ERROR

        if not connection_params["is_srv"]:
            # For SRV connections the hostname is a DNS namespace (e.g.
            # cluster0.mongodb.net), not a real host. Actual server addresses
            # are resolved at connection time and validated by
            # _make_safe_server_selector instead.
            # This check allows an early failure for obviously invalid connection strings for non SRV connections.
            valid_host, host_errors = self.is_database_host_valid(connection_params["host"], team_id)
            if not valid_host:
                return False, host_errors

        try:
            collection_names = get_collection_names(config, team_id=team_id)
            if len(collection_names) == 0:
                return False, "No collections found in database"
        except OperationFailure as e:
            capture_exception(e)
            return False, f"MongoDB authentication failed: {str(e)}"
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to connect to MongoDB database: {str(e)}"

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
            team_id=inputs.team_id,
            database_name=config.database_name,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MONGO_DB,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["mongo"],
            label="MongoDB",
            caption="Enter your MongoDB connection string to automatically pull your MongoDB data into the PostHog Data warehouse.",
            releaseStatus=ReleaseStatus.GA,
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
                        placeholder="mongodb://username:password@host:port/database?authSource=admin&tls=true",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="database_name",
                        label="Database name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="my_database",
                        caption=(
                            "Only needed if your connection string doesn't already include the database "
                            "(Atlas `mongodb+srv://...` strings usually don't)."
                        ),
                        secret=False,
                    ),
                ],
            ),
        )
