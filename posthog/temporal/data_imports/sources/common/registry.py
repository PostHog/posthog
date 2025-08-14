from typing import TYPE_CHECKING
from posthog.warehouse.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.temporal.data_imports.sources.common.base import BaseSource


class SourceRegistry:
    """Registry for all available data warehouse sources"""

    _sources: dict[ExternalDataSourceType, "BaseSource"] = {}

    @classmethod
    def register(cls, source_class: type["BaseSource"]):
        source_class_instance = source_class()
        source_type = source_class_instance.source_type

        cls._sources[source_type] = source_class_instance

        return source_class

    @classmethod
    def get_source(cls, source_type: ExternalDataSourceType) -> "BaseSource":
        """Get a source instance by type"""

        if source_type not in cls._sources:
            raise ValueError(f"Unknown source type: {source_type}")
        return cls._sources[source_type]

    @classmethod
    def get_all_sources(cls) -> dict[ExternalDataSourceType, "BaseSource"]:
        """Get all registered sources"""

        return cls._sources

    @classmethod
    def is_registered(cls, source_type: ExternalDataSourceType) -> bool:
        """Check if a source type is registered"""

        return source_type in cls._sources

    @classmethod
    def get_registered_types(cls) -> list[ExternalDataSourceType]:
        """Get all registered source types"""

        return list(cls._sources.keys())
