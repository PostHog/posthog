import itertools
from collections.abc import Iterator

from pydantic import BaseModel

import posthog.schema


def _all_subclasses(cls: type) -> Iterator[type]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _all_subclasses(subclass)


def _deferred_model_classes() -> Iterator[type[BaseModel]]:
    """Yield every schema model class that still defers its core-schema build.

    Skip the two injected base classes — they are abstract carriers of defer_build
    (RootModel still has an unbound TypeVar) and can't be built themselves.
    """
    bases = (posthog.schema.BaseModel, posthog.schema.RootModel)
    seen: set[type] = set()

    # Two sources, both needed: `vars(posthog.schema)` (restricted to classes actually
    # defined in the module, not pydantic's own re-imported bases) covers every class
    # defined directly in posthog.schema, and the `__subclasses__()` walk covers
    # subclasses defined elsewhere (e.g. posthog.hogql_queries.legacy_compatibility.filter_to_query)
    # that inherit defer_build=True via ConfigDict merging but are never module attributes.
    module_classes = (
        obj for obj in vars(posthog.schema).values() if isinstance(obj, type) and obj.__module__ == "posthog.schema"
    )
    candidates = itertools.chain(
        module_classes, _all_subclasses(posthog.schema.BaseModel), _all_subclasses(posthog.schema.RootModel)
    )
    for obj in candidates:
        if obj in seen:
            continue
        seen.add(obj)
        if issubclass(obj, BaseModel) and obj not in bases and not obj.__pydantic_complete__:
            yield obj


def build_all_schema_models() -> None:
    """Eagerly build the deferred core schemas of every model in posthog.schema.

    The generated models defer core-schema building to first use (see
    bin/patch-schema-defer-build.py), which keeps imports cheap for processes that only
    ever touch a few models (celery, temporal, CLI, pytest). Web pods should instead pay
    the full build once, pre-fork and behind readiness, so no worker handles its first
    live request after a deploy against unbuilt models — wsgi.py and asgi.py call this
    from their module-load warm block.
    """
    for obj in _deferred_model_classes():
        obj.model_rebuild()
