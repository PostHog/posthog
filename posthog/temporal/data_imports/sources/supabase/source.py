import re
from typing import Optional

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
from posthog.temporal.data_imports.sources.postgres.source import PostgresSource

from products.data_warehouse.backend.types import ExternalDataSourceType

_SourceField = (
    SourceFieldInputConfig
    | SourceFieldSwitchGroupConfig
    | SourceFieldSelectConfig
    | SourceFieldOauthConfig
    | SourceFieldFileUploadConfig
    | SourceFieldSSHTunnelConfig
)

# Supabase's direct connection host (`db.<ref>.supabase.co`) is IPv6-only and so is
# unreachable from PostHog's IPv4 egress — by far the biggest cause of Supabase
# connection failures. Users need the connection pooler host instead.
_SUPABASE_DIRECT_HOST_RE = re.compile(r"^db\.[a-z0-9]+\.supabase\.co$", re.IGNORECASE)

_SUPABASE_POOLER_HOST_CAPTION = (
    "Use the **Session pooler** host from Supabase (Project settings → Database → "
    "Connection pooling), e.g. `aws-0-<region>.pooler.supabase.com`, with username "
    "`postgres.<project-ref>`. The direct host `db.<ref>.supabase.co` is IPv6-only and "
    "won't be reachable."
)


@SourceRegistry.register
class SupabaseSource(PostgresSource):
    def __init__(self):
        super().__init__(source_name="Supabase")

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUPABASE

    @staticmethod
    def _adjust_field(field: _SourceField) -> _SourceField:
        if isinstance(field, SourceFieldInputConfig) and field.name == "schema":
            return field.model_copy(update={"required": True, "label": "Schema", "caption": None})
        if isinstance(field, SourceFieldInputConfig) and field.name == "host":
            return field.model_copy(
                update={
                    "placeholder": "aws-0-us-east-1.pooler.supabase.com",
                    "caption": _SUPABASE_POOLER_HOST_CAPTION,
                }
            )
        return field

    @property
    def get_source_config(self) -> SourceConfig:
        fields = [self._adjust_field(field) for field in super().get_source_config.fields]

        return SourceConfig(
            name=SchemaExternalDataSourceType.SUPABASE,
            iconPath="/static/services/supabase.png",
            caption="Enter your Supabase credentials to automatically pull your data into the PostHog Data warehouse",
            docsUrl="https://posthog.com/tutorials/supabase-query",
            fields=fields,
            releaseStatus=ReleaseStatus.GA,
        )

    def validate_credentials(
        self, config: PostgresSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Catch the IPv6-only direct host before the generic Postgres connect attempt
        # times out with an opaque "could not connect to the host on the port given".
        if _SUPABASE_DIRECT_HOST_RE.match((config.host or "").strip()):
            return False, (
                "This looks like the Supabase direct database host (db.<ref>.supabase.co), which is "
                "IPv6-only and unreachable from PostHog. Use the Session pooler host instead "
                "(aws-0-<region>.pooler.supabase.com) with username postgres.<project-ref> — find it "
                "under Project settings → Database → Connection pooling."
            )
        return super().validate_credentials(config, team_id, schema_name=schema_name)
