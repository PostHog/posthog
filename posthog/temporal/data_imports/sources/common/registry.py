import importlib
from typing import TYPE_CHECKING

from products.data_warehouse.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.temporal.data_imports.sources.common.base import AnySource


def _get_source_module_path(source_type: ExternalDataSourceType) -> str:
    """Convert ExternalDataSourceType enum to module path"""
    # Map enum names to module paths
    # e.g., CUSTOMERIO -> customer_io, GITHUB -> github, etc.
    name = source_type.name.lower()

    # Handle special cases
    module_mapping = {
        "customerio": "customer_io",
        "googleads": "google_ads",
        "googlesheets": "google_sheets",
        "metaads": "meta_ads",
        "linkedinads": "linkedin_ads",
        "redditads": "reddit_ads",
        "tiktokads": "tiktok_ads",
        "bingads": "bing_ads",
        "revenuecat": "revenuecat",
        "temporalio": "temporalio",
    }

    module_name = module_mapping.get(name, name)
    return f"posthog.temporal.data_imports.sources.{module_name}.source"


class SourceRegistry:
    """Registry for all available data warehouse sources"""

    _sources: dict[ExternalDataSourceType, "AnySource"] = {}
    _imported_modules: set[str] = set()

    @classmethod
    def register(cls, source_class: type["AnySource"]):
        source_class_instance = source_class()
        source_type = source_class_instance.source_type

        cls._sources[source_type] = source_class_instance

        return source_class

    @classmethod
    def _ensure_source_loaded(cls, source_type: ExternalDataSourceType) -> None:
        """Dynamically import the source module if not already loaded"""
        if source_type in cls._sources:
            return

        module_path = _get_source_module_path(source_type)
        if module_path in cls._imported_modules:
            # Module was imported but source wasn't registered - this shouldn't happen
            raise ValueError(f"Source type {source_type} module was imported but source was not registered")

        try:
            importlib.import_module(module_path)
            cls._imported_modules.add(module_path)

            # After importing, the @SourceRegistry.register decorator should have registered it
            if source_type not in cls._sources:
                raise ValueError(f"Source type {source_type} was not registered after importing {module_path}")
        except ImportError as e:
            raise ValueError(f"Failed to import source module for {source_type}: {e}") from e

    @classmethod
    def get_source(cls, source_type: ExternalDataSourceType) -> "AnySource":
        """Get a source instance by type, dynamically importing if needed"""

        cls._ensure_source_loaded(source_type)
        return cls._sources[source_type]

    @classmethod
    def get_all_sources(cls) -> dict[ExternalDataSourceType, "AnySource"]:
        """Get all registered sources, loading all available sources if needed"""

        # Load all sources that haven't been loaded yet
        for source_type in ExternalDataSourceType:
            if source_type not in cls._sources:
                try:
                    cls._ensure_source_loaded(source_type)
                except (ValueError, ImportError):
                    # Skip sources that don't exist or fail to load
                    continue

        return cls._sources

    @classmethod
    def is_registered(cls, source_type: ExternalDataSourceType) -> bool:
        """Check if a source type is registered, dynamically importing if needed"""

        if source_type in cls._sources:
            return True

        # Try to load it dynamically
        try:
            cls._ensure_source_loaded(source_type)
            return source_type in cls._sources
        except (ValueError, ImportError):
            return False

    @classmethod
    def get_registered_types(cls) -> list[ExternalDataSourceType]:
        """Get all registered source types"""

        return list(cls._sources.keys())
