from functools import cache

from posthog.products import load_product_modules

from ..facade.contracts import DigestSource

SOURCES_MODULE = "facade.data_catalog_digest"
SOURCES_ATTRIBUTE = "DIGEST_SOURCES"


@cache
def load_digest_sources() -> tuple[DigestSource, ...]:
    """Every source a product declares in `backend/facade/data_catalog_digest.py`, sorted by name."""
    sources = [
        source for module in load_product_modules(SOURCES_MODULE) for source in getattr(module, SOURCES_ATTRIBUTE, ())
    ]
    return tuple(sorted(sources, key=lambda source: source.name))
