#!/usr/bin/env python3
"""Turn protoc's absolute imports into relative ones so generated stubs import from any package path.

protoc emits `from personhog.types.v1 import common_pb2`, which only resolves when the
proto root is on sys.path. Rewriting to `from ....personhog.types.v1 import common_pb2`
lets the stubs live under posthog.personhog_client.proto.generated.
"""

import re
import sys
from pathlib import Path


def relativize(out_dir: Path) -> None:
    packages = [out_dir, *filter(Path.is_dir, out_dir.rglob("*"))]
    roots = sorted(p.name for p in packages if p.parent == out_dir)
    if not roots:
        raise SystemExit(f"{out_dir}: no generated package directories found")
    root_pattern = re.compile(rf"^from ({'|'.join(map(re.escape, roots))})\b", re.MULTILINE)

    for module in out_dir.rglob("*.py"):
        dots = "." * len(module.relative_to(out_dir).parts)
        module.write_text(root_pattern.sub(rf"from {dots}\1", module.read_text()))

    for package in packages:
        children = [p.name for p in package.iterdir() if p.is_dir()] + [p.stem for p in package.glob("*_pb2.py")]
        (package / "__init__.py").write_text("")
        (package / "__init__.pyi").write_text(f"from . import {', '.join(sorted(children))}\n")


if __name__ == "__main__":
    relativize(Path(sys.argv[1]))
