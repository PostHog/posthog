from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypeVar, Generic
from posthog.schema import SourceConfig
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.generated_configs import get_config_for_source
from posthog.temporal.data_imports.pipelines.source.config import Config
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse

if TYPE_CHECKING:
    from posthog.warehouse.models import ExternalDataSource

ConfigType = TypeVar("ConfigType", bound=Config)


class BaseSource(ABC, Generic[ConfigType]):
    """Base class for all data import sources"""

    @property
    @abstractmethod
    def source_type(self) -> "ExternalDataSource.Type":
        raise NotImplementedError()

    @property
    def config_class(self) -> type[ConfigType]:
        config = get_config_for_source(self.source_type)
        if not config:
            raise ValueError(f"Config class for {self.source_type} does not exist in SOURCE_CONFIG_MAPPING")

        return config

    @abstractmethod
    def source_for_pipeline(self, config: ConfigType, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()

    def get_schemas(self, config: ConfigType) -> list[SourceSchema]:
        raise NotImplementedError()

    def get_source_config(self) -> SourceConfig:
        from posthog.warehouse.api.available_sources import AVAILABLE_SOURCES

        return AVAILABLE_SOURCES[self.source_type]

    def parse_config(self, job_inputs: dict) -> ConfigType:
        return self.config_class.from_dict(job_inputs)

    @abstractmethod
    def validate_credentials(self, config: ConfigType) -> bool:
        """Check whether the provided credentials are valid for this source"""
        return True
