from collections.abc import Iterator

from pydantic import BaseModel

import posthog.schema


def _all_subclasses(cls: type) -> Iterator[type]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _all_subclasses(subclass)


def _deferred_model_classes() -> Iterator[type[BaseModel]]:
    """Yield every schema model class that still defers its core-schema build.

    Two sources, both needed: `vars(posthog.schema)` covers every class defined directly
    in the module, and the `__subclasses__()` walk covers subclasses defined elsewhere
    (e.g. `posthog.hogql_queries.legacy_compatibility.filter_to_query`) that inherit
    `defer_build=True` via ConfigDict merging but are never module attributes of
    posthog.schema. Skip the two injected base classes — they are abstract carriers of
    defer_build (RootModel still has an unbound TypeVar) and can't be built themselves.
    """
    bases = (posthog.schema.BaseModel, posthog.schema.RootModel)
    seen: set[type] = set()

    def module_classes() -> Iterator[type]:
        # Restrict to classes defined in posthog.schema, not pydantic's own re-imported
        # bases (e.g. the `_PydanticBaseModel`/`_PydanticRootModel` aliases live here too).
        for obj in vars(posthog.schema).values():
            if isinstance(obj, type) and obj.__module__ == "posthog.schema":
                yield obj

    def candidates() -> Iterator[type]:
        yield from module_classes()
        yield from _all_subclasses(posthog.schema.BaseModel)
        yield from _all_subclasses(posthog.schema.RootModel)

    for obj in candidates():
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
