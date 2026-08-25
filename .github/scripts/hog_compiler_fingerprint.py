#!/usr/bin/env python3
"""Print a cache-key fingerprint of the hog compiler, as `hash=<hex>` for $GITHUB_OUTPUT.

The Jest suites cache compiled hog bytecode keyed by the snippet's source, which stays correct
only while the compiler emits the same bytecode for that source. A fixed list of paths cannot
express that: the closure already reaches `posthog/celery.py` and `posthog/schema_enums.py`, and
nothing stops it reaching further. So import the compiler and hash whatever it actually loaded.
"""

import os
import sys
import hashlib
from collections.abc import Iterable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def select_paths(module_files: Iterable[str | None], repo_root: str, self_file: str) -> list[str]:
    """Repo-relative paths of the loaded first-party modules, minus this script.

    Third-party packages are pinned by uv.lock and none of them shape emitted bytecode, so they
    stay out: including them would invalidate the cache on every dependency bump.

    This script is dropped by path rather than by module name, because multiprocessing registers
    the entry module a second time as `__mp_main__` — excluding `__main__` alone lets it back in,
    and then every edit here invalidates every cache.
    """
    prefix = repo_root + os.sep
    paths = {
        os.path.relpath(path, repo_root)
        for path in module_files
        if path and path.startswith(prefix) and "site-packages" not in path
    }
    return sorted(paths - {os.path.relpath(self_file, repo_root)})


def main() -> None:
    # Running a script puts its own directory on the path, not the repo root.
    sys.path.insert(0, REPO_ROOT)
    # This import is what populates the closure read below.
    from posthog.hogql.compiler.bytecode import create_bytecode  # noqa: F401

    paths = select_paths(
        (getattr(module, "__file__", None) for module in list(sys.modules.values())),
        REPO_ROOT,
        os.path.abspath(__file__),
    )
    if not paths:
        raise SystemExit("no first-party compiler modules found — refusing to emit an empty key")

    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode())
        with open(os.path.join(REPO_ROOT, path), "rb") as handle:
            digest.update(handle.read())

    sys.stdout.write(f"hash={digest.hexdigest()[:16]}\n")
    sys.stderr.write(f"fingerprinted {len(paths)} compiler modules\n")


if __name__ == "__main__":
    main()
