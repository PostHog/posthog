from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.temporal.data_imports.sources.common.base import BaseSource
    from posthog.warehouse.models import ExternalDataSource


class SourceRegistry:
    """Registry for all available data warehouse sources"""

    _sources: dict["ExternalDataSource.Type", type["BaseSource"]] = {}

    @classmethod
    def register(cls, source_class: type["BaseSource"]):
        source_type = getattr(source_class, "source_type", None)
        if source_type is None:
            raise ValueError(f"{source_class} must have a 'source_type' attribute")

        cls._sources[source_type] = source_class

        return source_class

    @classmethod
    def get_source(cls, source_type: "ExternalDataSource.Type") -> "BaseSource":
        """Get a source instance by type"""

        if source_type not in cls._sources:
            raise ValueError(f"Unknown source type: {source_type}")
        return cls._sources[source_type]()

    @classmethod
    def get_all_sources(cls) -> dict["ExternalDataSource.Type", "BaseSource"]:
        """Get all registered sources"""

        return {k: v() for k, v in cls._sources.items()}

    @classmethod
    def is_registered(cls, source_type: "ExternalDataSource.Type") -> bool:
        """Check if a source type is registered"""

        return source_type in cls._sources

    @classmethod
    def get_registered_types(cls) -> list["ExternalDataSource.Type"]:
        """Get all registered source types"""

        return list(cls._sources.keys())
