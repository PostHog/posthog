"""Collection of the root URL patterns that products declare for themselves.

`register_routes(routers)` in `products/<product>/backend/routes.py` covers DRF routers only.
A plain Django path has no router to register onto, so a product declares one in the same module
as a `urlpatterns` list, and `posthog/urls.py` mounts every product's list in one slot.
"""

from collections.abc import Iterable
from types import ModuleType

from django.urls import URLPattern, URLResolver
from django.urls.resolvers import RegexPattern

from posthog.products import load_product_modules


class ProductRouteError(Exception):
    """A product root URL pattern outside the prefixes reserved for that product."""


class ProductRootRoutes:
    """The root patterns products declare, and the prefix rule they must satisfy."""

    # A product route in core's namespace can shadow a core route, and which one wins would then
    # depend on app iteration order. Reserving a prefix per product removes both.
    PREFIX_TEMPLATES: tuple[str, ...] = ("api/{product}/", "webhooks/{product}/")

    @staticmethod
    def _product_name(routes_module_name: str) -> str:
        """`products.stamphog.backend.routes` -> `stamphog`."""
        return routes_module_name.split(".")[1]

    @staticmethod
    def _route_of(pattern: URLPattern | URLResolver) -> str:
        """The declared route of a pattern, without the regex anchor.

        `path()` carries the route string. `re_path()`, which `opt_slash_path()` builds on,
        carries the regex, and that regex starts with `^` whenever it is anchored.
        """
        return str(pattern.pattern).removeprefix("^")

    @staticmethod
    def _is_unanchored_regex(pattern: URLPattern | URLResolver) -> bool:
        """Whether Django will look for this pattern anywhere in the path.

        A `RegexPattern` that does not end in `$` is matched with `re.search`, so a regex without
        a leading `^` also matches a path that merely contains it. Its text would still start
        with the product's prefix, which is why the prefix check alone cannot catch this.
        `path()` builds a `RoutePattern`, which Django anchors itself.
        """
        return isinstance(pattern.pattern, RegexPattern) and not str(pattern.pattern).startswith("^")

    @classmethod
    def from_module(cls, routes_module: ModuleType) -> list[URLPattern | URLResolver]:
        """The root patterns one product's routes module declares, checked against the rule.

        The check raises at URL conf load rather than logging, so a bad prefix fails every
        process start and every test instead of silently shadowing a core route in production.
        """
        declared: Iterable[URLPattern | URLResolver] = getattr(routes_module, "urlpatterns", ())
        patterns = list(declared)
        product = cls._product_name(routes_module.__name__)
        allowed = tuple(template.format(product=product) for template in cls.PREFIX_TEMPLATES)

        for pattern in patterns:
            if cls._is_unanchored_regex(pattern):
                raise ProductRouteError(
                    f"Product {product!r} declares root URL pattern {str(pattern.pattern)!r} as an "
                    f"unanchored regex, which matches anywhere in the path. Start it with '^'"
                )
            route = cls._route_of(pattern)
            if not route.startswith(allowed):
                allowed_list = " or ".join(repr(prefix) for prefix in allowed)
                raise ProductRouteError(
                    f"Product {product!r} declares root URL pattern {route!r}, which must start with {allowed_list}"
                )
        return patterns

    @classmethod
    def collect(cls) -> list[URLPattern | URLResolver]:
        """Every product's root patterns, in one list for `posthog/urls.py` to splice in."""
        collected: list[URLPattern | URLResolver] = []
        for routes_module in load_product_modules("routes"):
            collected.extend(cls.from_module(routes_module))
        return collected
