import dataclasses
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar, Union

from posthog.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

from posthog.schema import (
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import ResumableData, SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.config import Config
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import get_config_for_source

from products.data_warehouse.backend.types import ExternalDataSourceType

MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP = "Required for Marketing analytics to work with this source."

ConfigType = TypeVar("ConfigType", bound=Config)
ConfigType_contra = TypeVar("ConfigType_contra", bound=Config, contravariant=True)

FieldType = Union[
    SourceFieldInputConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldFileUploadConfig,
    SourceFieldSSHTunnelConfig,
]

SourceCredentialsValidationResult = tuple[bool, str | None]


class _BaseSource(ABC, Generic[ConfigType]):
    """Base class for all data import sources.

    This class provides common functionality for all sources but does NOT define
    source_for_pipeline - use SimpleSource or ResumableSource instead.
    """

    @property
    @abstractmethod
    def source_type(self) -> ExternalDataSourceType:
        raise NotImplementedError()

    @property
    def _config_class(self) -> type[ConfigType]:
        config = get_config_for_source(self.source_type)
        if not config:
            raise ValueError(f"Config class for {self.source_type} does not exist in SOURCE_CONFIG_MAPPING")

        return config

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        """Returns the errors for which the source should be disabled on.

        Returns `dict[str, str | None]`:
            key = a partial error message to match on
            value = a friendly error message to show to users. We fallback to displaying the key when this is missing
        """

        return {}

    def get_schemas(
        self, config: ConfigType, team_id: int, with_counts: bool = False, names: list[str] | None = None
    ) -> list[SourceSchema]:
        raise NotImplementedError()

    @property
    @abstractmethod
    def get_source_config(self) -> SourceConfig:
        raise NotImplementedError()

    def parse_config(self, job_inputs: dict) -> ConfigType:
        return self._config_class.from_dict(job_inputs)

    def validate_config(self, job_inputs: dict) -> tuple[bool, list[str]]:
        return self._config_class.validate_dict(job_inputs)

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        return None

    def validate_credentials(
        self, config: ConfigType, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        """Check whether the provided credentials are valid for this source. Returns an optional error message"""
        return True, None


class SimpleSource(_BaseSource[ConfigType], Generic[ConfigType]):
    """Base class for sources with standard pipeline creation."""

    def source_for_pipeline(self, config: ConfigType, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()


class ResumableSource(_BaseSource[ConfigType], Generic[ConfigType, ResumableData]):
    """Base class for sources that support resumable full-refresh imports."""

    def source_for_pipeline(
        self, config: ConfigType, resumable_source_manager: ResumableSourceManager[ResumableData], inputs: SourceInputs
    ) -> SourceResponse:
        raise NotImplementedError()

    @abstractmethod
    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ResumableData]:
        raise NotImplementedError()


@dataclasses.dataclass
class WebhookCreationResult:
    success: bool
    error: str | None = None
    extra_inputs: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class WebhookDeletionResult:
    success: bool
    error: str | None = None


@dataclasses.dataclass
class ExternalWebhookInfo:
    """Info about an external webhook on the source (e.g. Stripe webhook endpoint)."""

    exists: bool
    url: str | None = None
    enabled_events: list[str] | None = None
    status: str | None = None
    description: str | None = None
    created_at: str | None = None
    error: str | None = None


class WebhookSource(_BaseSource[ConfigType], Generic[ConfigType]):
    """Base class for sources that support webhook based imports."""

    @property
    @abstractmethod
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        raise NotImplementedError()

    @abstractmethod
    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        raise NotImplementedError()

    def create_webhook(self, config: ConfigType, webhook_url: str, team_id: int) -> WebhookCreationResult:
        """Create a webhook on the external source pointing to our webhook_url.

        Returns a WebhookCreationResult. If the source doesn't support automatic
        webhook creation, returns a failed result so the user can set it up manually.
        """
        raise NotImplementedError()

    @property
    @abstractmethod
    def webhook_resource_map(self) -> dict[str, str]:
        """The schema mapping to use to be stored on the HogFunction for matching incoming webhooks with tables.
        In most cases this will likely just be the table name -> table name. But in the case of Stripe, it's the
        table name mapped to the Stripe object type"""
        raise NotImplementedError()

    def get_external_webhook_info(self, config: ConfigType, webhook_url: str) -> ExternalWebhookInfo | None:
        """Check the external source for webhook status.

        Returns None if the source doesn't support checking webhook info.
        Sources should override this to query their API (e.g. list Stripe webhook endpoints).
        """
        return None

    def delete_webhook(self, config: ConfigType, webhook_url: str) -> WebhookDeletionResult:
        """Delete the webhook on the external source that matches webhook_url.

        Sources should override this to call their API (e.g. delete Stripe webhook endpoint).
        Returns a WebhookDeletionResult indicating success or failure.
        """
        return WebhookDeletionResult(success=False, error="This source does not support automatic webhook deletion.")


AnySource = SimpleSource[ConfigType] | ResumableSource[ConfigType, ResumableData] | WebhookSource[ConfigType]
