from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.firebase.firestore import (
    FirebaseResumeConfig,
    firestore_source,
    get_collection_schemas,
    list_collection_ids,
    validate_service_account_credentials,
)
from posthog.temporal.data_imports.sources.generated_configs import FirebaseSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FirebaseSource(ResumableSource[FirebaseSourceConfig, FirebaseResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIREBASE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Service account credentials are invalid or expired. Please reconnect with a fresh service account JSON.",
            "403 Client Error: Forbidden": "Service account is missing the required Firestore permissions. Grant the 'Cloud Datastore User' role (or equivalent) to the service account.",
            "404 Client Error: Not Found": "The specified Firestore database does not exist for this project.",
            "Failed to authenticate with provided Firebase service account key": None,
            "Service account key must contain a project_id": None,
        }

    def get_schemas(
        self,
        config: FirebaseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
    ) -> list[SourceSchema]:
        database_id = config.database_id or "(default)"

        collection_schemas = get_collection_schemas(
            key_info=_key_info(config),
            database_id=database_id,
            collection_names=names,
        )

        return [
            SourceSchema(
                name=collection_id,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=collection_schemas[collection_id]["incremental_fields"],
                columns=collection_schemas[collection_id]["columns"],
                detected_primary_keys=["_id"],
            )
            for collection_id in collection_schemas
        ]

    def validate_credentials(
        self,
        config: FirebaseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        database_id = config.database_id or "(default)"
        try:
            validate_service_account_credentials(_key_info(config))
        except Exception as e:
            return False, str(e)

        try:
            list_collection_ids(_key_info(config), database_id=database_id)
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to connect to Firestore database: {e}"

        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FirebaseResumeConfig]:
        return ResumableSourceManager[FirebaseResumeConfig](inputs, FirebaseResumeConfig)

    def source_for_pipeline(
        self,
        config: FirebaseSourceConfig,
        resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return firestore_source(
            key_info=_key_info(config),
            database_id=config.database_id or "(default)",
            collection_id=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIREBASE,
            label="Firebase",
            caption="Sync collections from Cloud Firestore. Upload a Google Cloud service account JSON key with the **Cloud Datastore User** role (or equivalent Firestore read access).",
            iconPath="/static/services/firebase.png",
            docsUrl="https://posthog.com/docs/cdp/sources/firebase",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-firebase",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="key_file",
                        label="Google Cloud service account JSON key",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(
                            format=".json",
                            keys=["project_id", "private_key", "private_key_id", "client_email", "token_uri"],
                        ),
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="database_id",
                        label="Firestore database ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="(default)",
                        caption="Most projects only have one Firestore database. Leave blank or set to `(default)` unless you use named databases.",
                        secret=False,
                    ),
                ],
            ),
        )


def _key_info(config: FirebaseSourceConfig) -> dict[str, str]:
    return {
        "project_id": config.key_file.project_id,
        "private_key": config.key_file.private_key,
        "private_key_id": config.key_file.private_key_id,
        "client_email": config.key_file.client_email,
        "token_uri": config.key_file.token_uri,
    }
