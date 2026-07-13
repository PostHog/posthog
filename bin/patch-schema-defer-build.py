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
# The statics and helpers below work together to keep concurrent, lazy model_rebuild()
# calls safe: _build_lock serializes the actual mutation, _currently_building tracks
# per-thread reentrancy so a build's own hooks don't recurse into itself, and
# _walked_schema_nodes memoizes _build_reachable_model_classes so a batch build doesn't
# re-walk shared subgraphs. _DeferredBuildGuards and the BaseModel/RootModel subclasses
# below tie them to the three ways an unbuilt class's instance can otherwise leak past
# validation (model_construct, unpickling, and validator-created children through Any).
_RootT = TypeVar("_RootT")


def _ensure_built(cls: type[_PydanticBaseModel]) -> None:
    if not cls.__pydantic_complete__:
        cls.model_rebuild()


# Serializes model_rebuild calls: pydantic's model_rebuild mutates class attributes
# non-atomically, so concurrent rebuilds of the same (or cross-referencing) classes can
# observe a half-built class. Only ever taken on the unbuilt path (callers re-check
# __pydantic_complete__ first), so the built steady state costs nothing.
_build_lock = threading.RLock()

# Classes whose build is in progress on the current thread: a build triggers
# __get_pydantic_core_schema__ for every referenced model class (including, recursively,
# the one being built), and those hooks must not start a second build of the same class.
# Thread-local because the lock above only serializes the mutation itself — a thread
# waiting on the lock must not see another thread's in-progress set and skip its own build.
_currently_building = threading.local()


def _building_set() -> set[type]:
    building = getattr(_currently_building, "classes", None)
    if building is None:
        building = set()
        _currently_building.classes = building
    return building


def _reset_build_state_after_fork() -> None:
    # A child forked while another thread held _build_lock would inherit it permanently
    # held (fork only clones the calling thread), deadlocking its first lazy build. Web
    # and celery build eagerly pre-fork so they never hit this; the deliberately-lazy
    # fork points (e.g. dagster's multiprocessing/billiard workers) are the exposed ones.
    global _build_lock
    _build_lock = threading.RLock()
    _currently_building.classes = set()


os.register_at_fork(after_in_child=_reset_build_state_after_fork)


# Schema dict nodes already walked by _build_reachable_model_classes, keyed by id() with
# the node itself as the value. A shared sub-schema is reachable from many parents;
# without memoizing, a batch build (e.g. build_all_schema_models) re-walks the same
# subgraphs once per class that reaches them. Storing the node (not just its id) pins it
# alive for the life of the process, which is required for soundness: ids are only unique
# among live objects, so an id-only set would silently alias a freed node's id onto a
# later, unrelated node once the allocator recycled it — e.g. under model_rebuild(force=True),
# which replaces a class's schema and frees the old nodes. There are no in-repo
# force=True callers on schema models today, but the memo must hold regardless.
_walked_schema_nodes: dict[int, Any] = {}


def _build_reachable_model_classes(schema: Any) -> None:
    """Complete every model class reachable from a freshly built core schema.

    Building a parent inlines child models' schemas without completing the child classes
    themselves, yet the parent's validator constructs child *instances*. Dumping such an
    instance through an `Any`-typed field makes pydantic-core look up the child class's
    own serializer — a mock, which raises `TypeError: 'MockValSer' object cannot be
    converted to 'SchemaSerializer'` instead of building (pydantic 2.12). Completing the
    reachable graph guarantees every instance a validator can create is serializable.

    Note: a class's __pydantic_complete__ flag flips to True (via super().model_rebuild())
    before this walk finishes, so a lock-free reader on another thread can, in a narrow
    window, see a "complete" parent whose children haven't been walked yet. Only threaded
    lazy (non-eager-build) processes are exposed; the failure is loud (the same MockValSer
    TypeError) and self-heals once the walk catches up.
    """
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            node_id = id(node)
            if node_id in _walked_schema_nodes:
                continue
            _walked_schema_nodes[node_id] = node
            if node.get("type") == "model":
                cls = node.get("cls")
                if isinstance(cls, type) and issubclass(cls, _PydanticBaseModel) and not cls.__pydantic_complete__:
                    _ensure_built(cls)
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)


class _DeferredBuildGuards:
    """Keep 'every live instance has a fully built class' true under defer_build.

    pydantic-core's serializer does not lazily build (unlike validation), so an instance
    of an unbuilt class poisons any later dump that reaches it through an `Any`-typed
    field. The ways such an instance can come to exist are guarded here and in the
    per-class `model_construct` overrides below.
    """

    @classmethod
    def model_rebuild(cls, **kwargs: Any) -> bool | None:  # type: ignore[misc]
        if cls.__pydantic_complete__ and not kwargs.get("force"):  # type: ignore[attr-defined]
            return None
        with _build_lock:
            if cls.__pydantic_complete__ and not kwargs.get("force"):  # type: ignore[attr-defined]
                return None
            # One extra frame between the caller and pydantic's implementation. 0 is a
            # meaningful sentinel to pydantic ("don't walk parent frames at all"), so
            # only the default and positive depths get the extra frame added.
            depth = kwargs.get("_parent_namespace_depth", 2)
            kwargs["_parent_namespace_depth"] = depth + 1 if depth > 0 else depth
            building = _building_set()
            building.add(cls)
            try:
                result = super().model_rebuild(**kwargs)  # type: ignore[misc]
            finally:
                building.discard(cls)
            if result is True:
                _build_reachable_model_classes(cls.__pydantic_core_schema__)  # type: ignore[attr-defined]
            return result

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        # An external schema build referencing this class (another model's rebuild, or a
        # TypeAdapter such as temporal's pydantic payload converter) inlines this class's
        # schema and can then construct its instances — so complete the class itself too.
        if source is cls and not cls.__pydantic_complete__ and cls not in _building_set():  # type: ignore[attr-defined]
            cls.model_rebuild()  # type: ignore[attr-defined]
        # Inlined fallback for the deprecated super().__get_pydantic_core_schema__ shim
        # (PydanticDeprecatedSince211, slated for removal in pydantic V3): return the
        # class's own schema if pydantic already built one, else let the handler build it.
        schema = cls.__dict__.get("__pydantic_core_schema__")
        if schema is not None and not isinstance(schema, MockCoreSchema):
            return schema
        return handler(source)

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

    if "class _DeferredBuildGuards:" in source:
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
    # The MockCoreSchema import below couples posthog.schema (the most-imported module in
    # the codebase) to a pydantic private internal — a pydantic bump that moves it makes
    # `import posthog.schema` raise ImportError everywhere. Failure is loud and CI-caught;
    # the embedded comment points a future bumper at this script and at the
    # subprocess-based tests in posthog/test/test_schema_defer_build.py to run on the bump.
    mock_core_schema_pointer_comment = (
        "# Private pydantic internal: see bin/patch-schema-defer-build.py for why, and\n"
        "# run posthog/test/test_schema_defer_build.py on any pydantic version bump.\n"
    )
    pydantic_import = (
        "import os\n"
        "import threading\n\n"
        f"from pydantic import {', '.join(sorted(names))}\n"
        "from pydantic import BaseModel as _PydanticBaseModel\n"
        "from pydantic import RootModel as _PydanticRootModel\n"
        f"{mock_core_schema_pointer_comment}"
        "from pydantic._internal._mock_val_ser import MockCoreSchema"
    )
    source = source[: match.start()] + pydantic_import + source[match.end() :]

    match, typing_names = parse_import("typing")
    merged = sorted(set(typing_names) | {"Any", "Generic", "Self", "TypeVar"})
    source = source[: match.start()] + f"from typing import {', '.join(merged)}" + source[match.end() :]

    # Insert the deferred base classes after the import block (the schema_enums import is
    # the last import; its closing paren is the first line that is exactly ")").
    enums_import_start = source.index("from posthog.schema_enums import (")
    insert_at = source.index("\n)\n", enums_import_start) + len("\n)\n")
    generated_tail = source[insert_at:]

    tail_lines = generated_tail.split("\n")
    stripped_tail_lines = [line for line in tail_lines if not re.fullmatch(r"\w+\.model_rebuild\(\)", line)]
    # If a datamodel-code-generator upgrade changes the emitted rebuild-call form (trailing
    # comment, argument, indentation), the narrower fullmatch above silently no-ops instead
    # of failing — leaving eager model_rebuild() calls in place that claw back most of the
    # deferred-build win. Scoped to the generated tail only: DEFERRED_BASE's own
    # model_rebuild() calls are part of the deferred-build machinery, not generated code.
    surviving_rebuild_calls = [line for line in stripped_tail_lines if re.search(r"\.model_rebuild\(", line)]
    if surviving_rebuild_calls:
        sys.exit(
            "patch-schema-defer-build: model_rebuild() calls survived the strip filter "
            f"(datamodel-code-generator output format may have changed): {surviving_rebuild_calls}"
        )
    source = source[:insert_at] + "\n" + DEFERRED_BASE + "\n".join(stripped_tail_lines)
    SCHEMA_PATH.write_text(source)
    print("patched posthog/schema.py: defer_build base classes injected, model_rebuild() calls dropped")


if __name__ == "__main__":
    main()
