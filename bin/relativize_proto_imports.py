#!/usr/bin/env python3
"""Turn protoc's absolute imports into relative ones so generated stubs import from any package path.

protoc emits `from personhog.types.v1 import common_pb2`, which only resolves when the
proto root is on sys.path. Rewriting to `from ....personhog.types.v1 import common_pb2`
lets the stubs live under posthog.personhog_client.proto.generated. Every directory also
gets an empty `__init__.py` and an `__init__.pyi` re-exporting its children, which type
checkers need to resolve the package structure.
"""

import re
import sys
from pathlib import Path


def relativize(out_dir: Path) -> None:
    roots = sorted(p.name for p in out_dir.iterdir() if p.is_dir() and p.name != "__pycache__")
    root_pattern = re.compile(rf"^from ({'|'.join(map(re.escape, roots))})(\.|\s)", re.MULTILINE)
    bare_import = re.compile(rf"^import ({'|'.join(map(re.escape, roots))})(\.|\s|$)", re.MULTILINE)

    for module in out_dir.rglob("*.py"):
        if module.name == "__init__.py":
            continue
        source = module.read_text()
        if bare_import.search(source):
            raise SystemExit(f"{module}: bare `import <root>` is not supported, expected `from ... import`")
        depth = len(module.relative_to(out_dir).parts)
        dots = "." * depth
        module.write_text(root_pattern.sub(rf"from {dots}\1\2", source))

    for package in [out_dir, *(p for p in out_dir.rglob("*") if p.is_dir() and p.name != "__pycache__")]:
        subpackages = [p.name for p in package.iterdir() if p.is_dir() and p.name != "__pycache__"]
        modules = [p.stem for p in package.glob("*_pb2.py")]
        (package / "__init__.py").write_text("")
        (package / "__init__.pyi").write_text(f"from . import {', '.join(sorted(subpackages + modules))}\n")


if __name__ == "__main__":
    relativize(Path(sys.argv[1]))
