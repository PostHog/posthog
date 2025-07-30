from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Union
from posthog.schema import (
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldFileUploadConfig,
    SourceFieldSSHTunnelConfig,
)
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import get_config_for_source
from posthog.temporal.data_imports.sources.common.config import Config
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.warehouse.models import ExternalDataSource

ConfigType = TypeVar("ConfigType", bound=Config)

FieldType = Union[
    SourceFieldInputConfig,
    SourceFieldSwitchGroupConfig,
    SourceFieldSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldFileUploadConfig,
    SourceFieldSSHTunnelConfig,
]


class BaseSource(ABC, Generic[ConfigType]):
    """Base class for all data import sources"""

    @property
    @abstractmethod
    def source_type(self) -> ExternalDataSource.Type:
        raise NotImplementedError()

    @property
    def _config_class(self) -> type[ConfigType]:
        config = get_config_for_source(self.source_type)
        if not config:
            raise ValueError(f"Config class for {self.source_type} does not exist in SOURCE_CONFIG_MAPPING")

        return config

    def source_for_pipeline(self, config: ConfigType, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()

    def get_schemas(self, config: ConfigType, team_id: int) -> list[SourceSchema]:
        raise NotImplementedError()

    @property
    @abstractmethod
    def get_source_config(self) -> SourceConfig:
        raise NotImplementedError()

    def parse_config(self, job_inputs: dict) -> ConfigType:
        return self._config_class.from_dict(job_inputs)

    def validate_config(self, job_inputs: dict) -> tuple[bool, list[str]]:
        return self._config_class.validate_dict(job_inputs)

    def validate_credentials(self, config: ConfigType, team_id: int) -> tuple[bool, str | None]:
        """Check whether the provided credentials are valid for this source. Returns an optional error message"""
        return True, None
