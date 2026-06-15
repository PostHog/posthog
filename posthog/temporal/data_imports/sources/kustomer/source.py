from typing import Optional, cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import KustomerSourceConfig
from posthog.temporal.data_imports.sources.kustomer.kustomer import (
    KustomerResumeConfig,
    kustomer_source,
    validate_credentials as validate_kustomer_credentials,
)
from posthog.temporal.data_imports.sources.kustomer.settings import ENDPOINTS

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KustomerSource(ResumableSource[KustomerSourceConfig, KustomerResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KUSTOMER

    @property
    def connection_host_fields(self) -> list[str]:
        # `org_name` determines the host the stored API key is sent to;
        # retargeting it must re-require the key.
        return ["org_name"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Kustomer authentication failed. Please check your API key and organization name.",
            "403 Client Error: Forbidden for url": "Kustomer denied access. Please check that your API key's roles grant read access to this dataset.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KUSTOMER,
            label="Kustomer",
            caption="""Enter your Kustomer API credentials to pull your Kustomer support data into the PostHog Data warehouse.

Your organization name is the first part of your Kustomer URL — for `myorg.kustomerapp.com` enter `myorg`. Create an API key in Kustomer under Settings > Security > API Keys with read roles for the data you want to sync (e.g. `org.user.read`).""",
            iconPath="/static/services/kustomer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/kustomer",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="org_name",
                        label="Organization name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="myorg",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: KustomerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # GET list endpoints have no updated-since filter; full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: KustomerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_kustomer_credentials(config.org_name, config.api_key):
            return True, None

        return False, "Invalid Kustomer API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KustomerResumeConfig]:
        return ResumableSourceManager[KustomerResumeConfig](inputs, KustomerResumeConfig)

    def source_for_pipeline(
        self,
        config: KustomerSourceConfig,
        resumable_source_manager: ResumableSourceManager[KustomerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kustomer_source(
            org_name=config.org_name,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
