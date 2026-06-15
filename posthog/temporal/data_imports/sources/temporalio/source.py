from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig
from posthog.temporal.data_imports.sources.temporalio.temporalio import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TemporalIOResource,
    TemporalIOResumeConfig,
    temporalio_source,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TemporalIOSource(ResumableSource[TemporalIOSourceConfig, TemporalIOResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEMPORALIO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # rustls surfaces mTLS rejections as TLS alert names inside the tonic transport
        # error. These are credential problems — retrying can never recover.
        return {
            # The Temporal core builds the connection target from the configured host:port. An empty
            # or scheme-only host yields no parseable host — a config problem retrying never fixes.
            "invalid target URL: empty host": "Temporal could not connect because the configured host is empty or invalid. Update the source with the hostname of your Temporal namespace's gRPC endpoint (for example, your-namespace.account.tmprl.cloud) — without a protocol scheme or port.",
            "received fatal alert: UnknownCA": "Temporal rejected this source's client certificate because it is not signed by a certificate authority the namespace trusts. This usually means the namespace's CA certificates were rotated — update the source with a client certificate and key signed by the current CA.",
            "received fatal alert: CertificateExpired": "This source's client certificate has expired. Update the source with a renewed client certificate and key.",
            "received fatal alert: CertificateRevoked": "This source's client certificate has been revoked. Update the source with a new client certificate and key.",
            "received fatal alert: BadCertificate": "Temporal rejected this source's client certificate as invalid. Update the source with a valid client certificate and key.",
            "received fatal alert: CertificateUnknown": "Temporal rejected this source's client certificate. Update the source with a valid client certificate and key.",
            "invalid peer certificate": "The Temporal server's certificate could not be verified. Check the host and port point at your Temporal namespace's gRPC endpoint.",
        }

    def get_schemas(
        self,
        config: TemporalIOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TemporalIOResumeConfig]:
        return ResumableSourceManager[TemporalIOResumeConfig](inputs, TemporalIOResumeConfig)

    def source_for_pipeline(
        self,
        config: TemporalIOSourceConfig,
        resumable_source_manager: ResumableSourceManager[TemporalIOResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return temporalio_source(
            config,
            TemporalIOResource(inputs.schema_name),
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEMPORAL_IO,
            label="Temporal.io",
            iconPath="/static/services/temporal.png",
            docsUrl="https://posthog.com/docs/cdp/sources/temporal",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="namespace",
                        label="Namespace",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="encryption_key",
                        label="Encryption key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="server_client_root_ca",
                        label="Server client root CA",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="client_certificate",
                        label="Client certificate",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="client_private_key",
                        label="Client private key",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
