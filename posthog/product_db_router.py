from __future__ import annotations

from functools import lru_cache

from django.conf import settings
from django.core.checks import Error, register

from posthog.product_db_config import ProductDBRoute, load_product_db_routes
from posthog.settings.base_variables import TEST


@lru_cache(maxsize=1)
def get_product_db_routes() -> tuple[ProductDBRoute, ...]:
    return load_product_db_routes(settings.BASE_DIR)


class ProductDBRouter:
    def __init__(self, routes: tuple[ProductDBRoute, ...] | None = None):
        configured_routes = routes if routes is not None else get_product_db_routes()
        self.routes = tuple(route for route in configured_routes if f"{route.database}_db_writer" in settings.DATABASES)
        self._product_db_aliases = frozenset(
            alias
            for route in self.routes
            for alias in (f"{route.database}_db_writer", f"{route.database}_db_reader", f"{route.database}_db_direct")
        )

    def db_for_read(self, model, **hints):
        for route in self.routes:
            if route.routes_model(model):
                # In tests, reads go to the writer so they share the same
                # connection and transaction — otherwise reads can't see
                # uncommitted writes within the same test.
                suffix = "_db_writer" if TEST else "_db_reader"
                return f"{route.database}{suffix}"
        return None

    def db_for_write(self, model, **hints):
        for route in self.routes:
            if route.routes_model(model):
                return f"{route.database}_db_writer"
        return None

    def allow_relation(self, obj1, obj2, **hints):
        db1 = self._db_for_model(obj1.__class__)
        db2 = self._db_for_model(obj2.__class__)
        if db1 is not None or db2 is not None:
            # If either model is routed, only allow if both resolve to the same DB
            return db1 == db2
        return None

    def _db_for_model(self, model_class: type) -> str | None:
        for route in self.routes:
            if route.routes_model(model_class):
                return route.database
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        for route in self.routes:
            if app_label == route.app_label:
                return db in (f"{route.database}_db_writer", f"{route.database}_db_direct")

        if db in self._product_db_aliases:
            return False

        return None


@register()
def check_product_db_routes(app_configs, **kwargs):
    errors: list[Error] = []

    routes = get_product_db_routes()
    app_label_to_database: dict[str, str] = {}

    for route in routes:
        existing = app_label_to_database.get(route.app_label)
        if existing is not None and existing != route.database:
            errors.append(
                Error(
                    f"product db route for '{route.app_label}' points to multiple databases",
                    hint="Ensure each product app has exactly one database in db_routing.yaml",
                    id="posthog.E003",
                )
            )
        app_label_to_database[route.app_label] = route.database

    return errors
