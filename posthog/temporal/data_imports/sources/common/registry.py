from typing import TYPE_CHECKING

from products.data_warehouse.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.temporal.data_imports.sources.common.base import AnySource


class SourceRegistry:
    """Registry for all available data warehouse sources"""

    _sources: dict[ExternalDataSourceType, "AnySource"] = {}

    @classmethod
    def register(cls, source_class: type["AnySource"]):
        source_class_instance = source_class()
        source_type = source_class_instance.source_type

        cls._sources[source_type] = source_class_instance

        return source_class

    @classmethod
    def get_source(cls, source_type: ExternalDataSourceType) -> "AnySource":
        """Get a source instance by type"""

        if source_type not in cls._sources:
            raise ValueError(f"Unknown source type: {source_type}")
        return cls._sources[source_type]

    @classmethod
    def get_all_sources(cls) -> dict[ExternalDataSourceType, "AnySource"]:
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
