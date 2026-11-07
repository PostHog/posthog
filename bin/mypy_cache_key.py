import os
import sys
import hashlib
from collections.abc import Iterator
from pathlib import Path


def config_files(root: Path) -> Iterator[Path]:
    def walk(directory: Path, matched_directory: bool = False) -> Iterator[Path]:
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for entry in children:
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
            except FileNotFoundError:
                continue
            child = Path(entry.path)
            matched = matched_directory or child.name in {"pyproject.toml", "mypy.ini"} or child == root / "uv.lock"
            if is_directory:
                yield from walk(child, matched)
            elif matched and not entry.is_dir():
                yield child

    yield from walk(root)


def config_hash(root: Path) -> str:
    # Match hashFiles' ordered hash of file hashes so existing caches remain usable.
    result = hashlib.sha256()
    found = False
    for file in config_files(root):
        with file.open("rb") as contents:
            result.update(hashlib.file_digest(contents, "sha256").digest())
        found = True
    return result.hexdigest() if found else ""


if __name__ == "__main__":
    sys.stdout.write(config_hash(Path.cwd()) + "\n")
