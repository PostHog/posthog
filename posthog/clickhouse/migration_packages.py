import importlib.util

from django.apps import apps

CORE_MIGRATIONS_PACKAGE = "posthog.clickhouse.migrations"


def get_clickhouse_migration_packages() -> list[str]:
    """ClickHouse migration packages to run, core first then opted-in products.

    A product opts in by creating ``products/<name>/backend/clickhouse/migrations/__init__.py``.
    Each package is numbered and tracked independently — infi keys applied state on the
    package name — so a product's ``0001_`` never collides with core's. Cross-package ordering
    is convention-based: core migrates first, products follow in INSTALLED_APPS order, and a
    product migration must only touch its own tables.
    """
    packages = [CORE_MIGRATIONS_PACKAGE]
    for config in apps.get_app_configs():
        if not config.name.startswith("products."):
            continue
        package = f"{config.name}.clickhouse.migrations"
        try:
            # find_spec raises ModuleNotFoundError when an intermediate package
            # (e.g. the product's `clickhouse` dir) doesn't exist — that just means
            # the product hasn't opted in.
            if importlib.util.find_spec(package) is not None:
                packages.append(package)
        except ModuleNotFoundError:
            continue
    return packages
