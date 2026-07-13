# ruff: noqa: T201 allow print statements in this build script
"""Patch posthog/schema.py to defer pydantic core-schema building to first use.

datamodel-code-generator emits ~900 plain pydantic BaseModel classes. Building every
model's core schema (validator + serializer) at import costs ~1.6s per process, paid by
anything that imports posthog.schema — web workers, celery, every pytest process — while
any single process only ever validates a small subset of the models. `defer_build=True`
moves that cost to first use per model, so unused models never pay it.

Two edits, applied after generation (run from bin/build-schema-python.sh):

1. Replace the generated `BaseModel` / `RootModel` imports with local subclasses that set
   `model_config = ConfigDict(defer_build=True)`. Per-class ConfigDicts merge with the
   parent config, so `extra="forbid"` etc. are preserved.

2. Drop the trailing `X.model_rebuild()` calls. They exist to resolve forward references
   for recursive models at import; with defer_build the (re)build happens lazily on first
   use, after the whole module is defined, so every forward reference resolves without an
   explicit rebuild — and keeping them would force eager builds of exactly the biggest
   model subgraphs.

The injected base classes also guarantee that any instance that can exist belongs to a
fully built class. Validation lazily builds a deferred model, but pydantic-core's
*serializer* does not: dumping an instance whose own class is unbuilt, nested inside
another model's `Any`-typed field, hits the Rust serializer fallback, which raises
`TypeError: 'MockValSer' object cannot be converted to 'SchemaSerializer'` instead of
building (pydantic 2.12). Instances of an unbuilt class arise three ways, each guarded:

- `model_construct` and `__setstate__` (unpickling) force a build first.
- A parent's validator constructs instances of child models whose schemas were inlined
  into the parent without completing the child classes themselves. Two hooks close this:
  `__get_pydantic_core_schema__` completes the class whenever an external schema build
  (another model's rebuild, or a `TypeAdapter` — e.g. temporal's pydantic payload
  converter) references it, and `model_rebuild` completes every model class reachable
  from the freshly built core schema — together, the full set of classes a validator
  can instantiate.

Web, celery, and temporal processes additionally build everything eagerly at boot — see
posthog/schema_build.py.
"""

import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "posthog" / "schema.py"

DEFERRED_BASE = '''\
_RootT = TypeVar("_RootT")


def _ensure_built(cls: type[_PydanticBaseModel]) -> None:
    if not cls.__pydantic_complete__:
        cls.model_rebuild()


def _build_reachable_model_classes(schema: Any) -> None:
    """Complete every model class reachable from a freshly built core schema.

    Building a parent inlines child models' schemas without completing the child classes
    themselves, yet the parent's validator constructs child *instances*. Dumping such an
    instance through an `Any`-typed field makes pydantic-core look up the child class's
    own serializer — a mock, which raises `TypeError: 'MockValSer' object cannot be
    converted to 'SchemaSerializer'` instead of building (pydantic 2.12). Completing the
    reachable graph guarantees every instance a validator can create is serializable.
    """
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") == "model":
                cls = node.get("cls")
                if isinstance(cls, type) and issubclass(cls, _PydanticBaseModel):
                    _ensure_built(cls)
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)


# Classes whose build is in progress: a build triggers __get_pydantic_core_schema__ for
# every referenced model class (including, recursively, the one being built), and those
# hooks must not start a second build of the same class.
_currently_building: set[type] = set()


class _DeferredBuildGuards:
    """Keep 'every live instance has a fully built class' true under defer_build.

    pydantic-core's serializer does not lazily build (unlike validation), so an instance
    of an unbuilt class poisons any later dump that reaches it through an `Any`-typed
    field. The ways such an instance can come to exist are guarded here and in the
    per-class `model_construct` overrides below.
    """

    @classmethod
    def model_rebuild(cls, **kwargs: Any) -> bool | None:  # type: ignore[misc]
        # One extra frame between the caller and pydantic's implementation.
        kwargs["_parent_namespace_depth"] = kwargs.get("_parent_namespace_depth", 2) + 1
        _currently_building.add(cls)
        try:
            result = super().model_rebuild(**kwargs)  # type: ignore[misc]
        finally:
            _currently_building.discard(cls)
        if result is not False and cls.__pydantic_complete__:  # type: ignore[attr-defined]
            _build_reachable_model_classes(cls.__pydantic_core_schema__)  # type: ignore[attr-defined]
        return result

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        # An external schema build referencing this class (another model's rebuild, or a
        # TypeAdapter such as temporal's pydantic payload converter) inlines this class's
        # schema and can then construct its instances — so complete the class itself too.
        if source is cls and not cls.__pydantic_complete__ and cls not in _currently_building:  # type: ignore[attr-defined]
            cls.model_rebuild()  # type: ignore[attr-defined]
        return super().__get_pydantic_core_schema__(source, handler)  # type: ignore[misc]

    def __setstate__(self, state: dict[Any, Any]) -> None:
        _ensure_built(type(self))
        super().__setstate__(state)  # type: ignore[misc]


class BaseModel(_DeferredBuildGuards, _PydanticBaseModel):
    # Core-schema building is deferred to first use: see bin/patch-schema-defer-build.py
    model_config = ConfigDict(defer_build=True)

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:
        _ensure_built(cls)
        return super().model_construct(_fields_set, **values)


class RootModel(_DeferredBuildGuards, _PydanticRootModel[_RootT], Generic[_RootT]):
    # Core-schema building is deferred to first use: see bin/patch-schema-defer-build.py
    model_config = ConfigDict(defer_build=True)

    @classmethod
    def model_construct(cls, root: _RootT, _fields_set: set[str] | None = None) -> Self:  # type: ignore[override]
        _ensure_built(cls)
        return super().model_construct(root, _fields_set=_fields_set)
'''


def main() -> None:
    source = SCHEMA_PATH.read_text()

    if "defer_build=True" in source:
        print("posthog/schema.py already patched for defer_build; nothing to do")
        return

    # Both import forms occur depending on formatting: a single line, or a parenthesized
    # multi-line block (fresh datamodel-codegen output wraps long import lists).
    def parse_import(module: str) -> tuple[re.Match, list[str]]:
        import_re = re.compile(
            rf"^from {module} import \(\n(?P<names>(?: .+\n)+)\)$|^from {module} import (?P<inline>.+)$", re.MULTILINE
        )
        match = import_re.search(source)
        if not match:
            sys.exit(f"patch-schema-defer-build: could not find the {module} import in posthog/schema.py")
        raw = match.group("names") or match.group("inline")
        names = [name.strip().rstrip(",") for name in raw.replace("\n", ",").split(",")]
        return match, [name for name in names if name]

    match, names = parse_import("pydantic")
    for required in ("BaseModel", "RootModel"):
        if required not in names:
            sys.exit(f"patch-schema-defer-build: expected {required} in the pydantic import")
    names = [name for name in names if name not in ("BaseModel", "RootModel")]
    if "ConfigDict" not in names:
        names.append("ConfigDict")
    pydantic_import = (
        f"from pydantic import {', '.join(sorted(names))}\n"
        "from pydantic import BaseModel as _PydanticBaseModel\n"
        "from pydantic import RootModel as _PydanticRootModel"
    )
    source = source[: match.start()] + pydantic_import + source[match.end() :]

    match, typing_names = parse_import("typing")
    merged = sorted(set(typing_names) | {"Any", "Generic", "Self", "TypeVar"})
    source = source[: match.start()] + f"from typing import {', '.join(merged)}" + source[match.end() :]

    # Insert the deferred base classes after the import block (the schema_enums import is
    # the last import; its closing paren is the first line that is exactly ")").
    enums_import_start = source.index("from posthog.schema_enums import (")
    insert_at = source.index("\n)\n", enums_import_start) + len("\n)\n")
    source = source[:insert_at] + "\n" + DEFERRED_BASE + source[insert_at:]

    lines = [line for line in source.split("\n") if not re.fullmatch(r"\w+\.model_rebuild\(\)", line)]
    SCHEMA_PATH.write_text("\n".join(lines))
    print("patched posthog/schema.py: defer_build base classes injected, model_rebuild() calls dropped")


if __name__ == "__main__":
    main()
