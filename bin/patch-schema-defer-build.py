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
"""

import re
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "posthog" / "schema.py"

DEFERRED_BASE = """\
_RootT = TypeVar("_RootT")


class BaseModel(_PydanticBaseModel):
    # Core-schema building is deferred to first use: see bin/patch-schema-defer-build.py
    model_config = ConfigDict(defer_build=True)


class RootModel(_PydanticRootModel[_RootT], Generic[_RootT]):
    # Core-schema building is deferred to first use: see bin/patch-schema-defer-build.py
    model_config = ConfigDict(defer_build=True)
"""


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
    merged = sorted(set(typing_names) | {"Generic", "TypeVar"})
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
