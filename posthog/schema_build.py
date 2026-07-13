from pydantic import BaseModel

import posthog.schema


def build_all_schema_models() -> None:
    """Eagerly build the deferred core schemas of every model in posthog.schema.

    The generated models defer core-schema building to first use (see
    bin/patch-schema-defer-build.py), which keeps imports cheap for processes that only
    ever touch a few models (celery, temporal, CLI, pytest). Web pods should instead pay
    the full build once, pre-fork and behind readiness, so no worker handles its first
    live request after a deploy against unbuilt models — wsgi.py and asgi.py call this
    from their module-load warm block.
    """
    # Restrict to classes defined in posthog.schema (not pydantic's own re-imported
    # bases), and skip the two injected base classes — they are abstract carriers of
    # defer_build (RootModel still has an unbound TypeVar) and can't be built themselves.
    bases = (posthog.schema.BaseModel, posthog.schema.RootModel)
    for obj in vars(posthog.schema).values():
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and obj.__module__ == "posthog.schema"
            and obj not in bases
            and not obj.__pydantic_complete__
        ):
            obj.model_rebuild()
