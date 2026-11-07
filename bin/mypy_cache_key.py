import sys
import stat
import hashlib
from collections.abc import Iterator
from pathlib import Path


def config_files(root: Path) -> Iterator[Path]:
    def walk(directory: Path, matched_directory: bool = False) -> Iterator[Path]:
        for child in sorted(directory.iterdir(), key=lambda entry: entry.name):
            try:
                child_stat = child.lstat()
            except FileNotFoundError:
                continue
            matched = matched_directory or child.name in {"pyproject.toml", "mypy.ini"} or child == root / "uv.lock"
            if stat.S_ISDIR(child_stat.st_mode):
                yield from walk(child, matched)
            elif matched and not child.is_dir():
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
