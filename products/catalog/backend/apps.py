from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "products.catalog.backend"
    label = "catalog"
    verbose_name = "Catalog"

    def ready(self) -> None:
        from . import signals  # noqa: F401
