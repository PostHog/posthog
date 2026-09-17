"""The root URL mounts that products declare for themselves.

`register_routes(routers)` in `products/<product>/backend/routes.py` covers DRF routers only.
A plain Django path has no router to register onto, so a product declares it in the same module
as an `api_urlpatterns` or `webhook_urlpatterns` list, with routes relative to the mount.
`posthog/urls.py` mounts both lists in one slot.
"""

from types import ModuleType

from django.core.exceptions import ImproperlyConfigured
from django.urls import URLResolver, include, path

from posthog.products import load_product_modules


class ProductRootRoutes:
    """The prefixes reserved per product, and the lists mounted under them."""

    # A product route in core's namespace can shadow a core route, and which one wins would then
    # depend on app iteration order. A mount per product removes both, because a route declared
    # inside the mount cannot address anything outside it.
    MOUNTS: tuple[tuple[str, str], ...] = (
        ("api_urlpatterns", "api/{product}/"),
        ("webhook_urlpatterns", "webhooks/{product}/"),
    )

    @staticmethod
    def _product_name(routes_module_name: str) -> str:
        """`products.stamphog.backend.routes` -> `stamphog`."""
        return routes_module_name.split(".")[1]

    @classmethod
    def from_module(cls, routes_module: ModuleType) -> list[URLResolver]:
        """The mounts one product's routes module asks for.

        `include()` gets the list, not the module, so Django sets no application namespace and
        `reverse("<name>")` keeps working unchanged.

        A module that still declares the flat `urlpatterns` raises instead of being skipped,
        because a skip would drop its routes and only show up as a 404 in production.
        """
        product = cls._product_name(routes_module.__name__)
        if hasattr(routes_module, "urlpatterns"):
            raise ImproperlyConfigured(
                f"Product {product!r} declares 'urlpatterns' in its routes module, which core no "
                f"longer mounts. Rename it to 'api_urlpatterns' or 'webhook_urlpatterns' and make "
                f"every route relative to 'api/{product}/' or 'webhooks/{product}/'"
            )

        mounts = []
        for attribute, prefix_template in cls.MOUNTS:
            declared = getattr(routes_module, attribute, None)
            if declared:
                mounts.append(path(prefix_template.format(product=product), include(declared)))
        return mounts

    @classmethod
    def collect(cls) -> list[URLResolver]:
        """Every product's mounts, for the one slot in `posthog/urls.py`."""
        collected: list[URLResolver] = []
        for routes_module in load_product_modules("routes"):
            collected.extend(cls.from_module(routes_module))
        return collected
