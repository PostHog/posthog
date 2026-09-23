"""Experimental: load Python bytecode from one LZ4-compressed, memory-mapped archive.

Build:  python -m bytecode_archive build --out /tmp/all.lz4 [--codec lz4|none] [--site] [--stdlib]
Use:    POSTHOG_BYTECODE_ARCHIVE=/tmp/all.lz4 python manage.py ...           (see manage.py)
        POSTHOG_BYTECODE_ARCHIVE_UNCHECKED=1  skips the per-module stat of the .py (immutable trees)

The finder only replaces *where the code object comes from*. Modules keep their real ``__file__``
and packages keep a real on-disk ``__path__``, so Django's file-based discovery (migrations,
templates, management commands), ``importlib.resources`` and anything reading data next to
``__file__`` keep working. Names not in the archive fall through to the normal finders, so
extension modules, namespace packages and anything skipped at build time still import.

File layout: header | top-level table (marshal) | per-top-level indexes (marshal) | blobs.
The top-level table maps ``top_name -> (index_offset, index_len)``; each per-top index maps
``module_name -> (blob_offset, blob_len, is_pkg, source_path, mtime_ns, size)`` and is only
unmarshalled the first time a module under that top-level name is requested. That keeps the
startup cost of a 40k-module archive at one small marshal load instead of a 5 MB one.

Measured (Sept 2026, TEST=1, bare django.setup(), best of 3 warm / 1 cold after a page-cache drop):

    pyc files on disk                 warm 1.53s   cold 2.79s
    first-party only, lz4             warm 1.49s   cold 2.07s
    first-party + site + stdlib, lz4  warm 1.42s   cold 2.16s   (262 MB, 49.9k modules, 3443 served at setup)
    first-party + site + stdlib, none warm 1.40s   cold 2.09s   (543 MB)

The warm win (~7%) is the path finder work that no longer happens (directory listings, stats,
per-module file opens); LZ4 decompression costs ~20ms across the boot. The cold win (~25%) is
reading one sequential file instead of ~3400 scattered ones. Checking the source mtime per
module costs nothing measurable, so the default stays checked.
"""

from __future__ import annotations

import io
import os
import sys
import mmap
import struct
import marshal
import importlib.abc
import importlib.util
from collections.abc import Iterable

MAGIC = b"PHBCA002"
_HEADER = struct.Struct("<8sIII")  # magic, codec id, top table length, total index length
CODECS = ("none", "lz4")
SKIP_DIRS = frozenset(
    {
        "test",
        "tests",
        "__pycache__",
        "node_modules",
        "idlelib",
        "tkinter",
        "turtledemo",
        "ensurepip",
        "lib2to3",
        "__phello__",
    }
)
EXT_SUFFIXES = (".so", ".pyd")


def _compressor(codec: str):
    if codec == "none":
        return lambda b: b
    import lz4.block

    return lambda b: lz4.block.compress(b, mode="high_compression", store_size=True)


def _decompressor(codec: str):
    if codec == "none":
        return lambda b: b
    import lz4.block

    return lz4.block.decompress


def _ext_stems(filenames: list[str]) -> set[str]:
    return {fn.split(".", 1)[0] for fn in filenames if fn.endswith(EXT_SUFFIXES)}


def _iter_tree(root: str, prefix: str):
    """Yield (module_name, abs_path, is_package) for every regular package/module under root.
    Directories without __init__.py are treated as namespace portions: not served themselves,
    but regular packages below them are."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".") and d.isidentifier())
        rel = os.path.relpath(dirpath, root)
        parts = [] if rel == "." else rel.split(os.sep)
        dotted = ".".join(p for p in [prefix, *parts] if p)
        is_regular_pkg = "__init__.py" in filenames
        ext = _ext_stems(filenames)
        if is_regular_pkg and dotted:
            yield dotted, os.path.join(dirpath, "__init__.py"), True
        if not is_regular_pkg and parts and not dotted:
            continue
        for fn in sorted(filenames):
            if not fn.endswith(".py") or fn == "__init__.py":
                continue
            stem = fn[:-3]
            if not stem.isidentifier() or stem in ext:
                continue
            if not is_regular_pkg and parts:
                # plain .py inside a namespace dir: served, the namespace parent comes from the path finder
                pass
            yield (f"{dotted}.{stem}" if dotted else stem), os.path.join(dirpath, fn), False


def _compile_one(args):
    name, path, is_pkg, codec = args
    compress = _compressor(codec)
    with open(path, "rb") as f:
        src = f.read()
    try:
        code = compile(src, path, "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        return None
    data = marshal.dumps(code)
    st = os.stat(path)
    return name, compress(data), is_pkg, path, st.st_mtime_ns, st.st_size, len(data)


def build(roots: Iterable[tuple[str, str]], out: str, codec: str = "lz4", workers: int | None = None) -> dict:
    """roots: (directory, dotted_prefix) pairs; prefix '' means the directory is a sys.path entry."""
    from concurrent.futures import ProcessPoolExecutor

    jobs = []
    seen: set[str] = set()
    for root, prefix in roots:
        for name, path, is_pkg in _iter_tree(os.path.abspath(root), prefix):
            if name in seen:
                continue
            seen.add(name)
            jobs.append((name, path, is_pkg, codec))
    per_top: dict[str, dict] = {}
    blobs = io.BytesIO()
    raw_total = 0
    skipped = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_compile_one, jobs, chunksize=64):
            if res is None:
                skipped += 1
                continue
            name, blob, is_pkg, path, mtime, size, raw = res
            raw_total += raw
            per_top.setdefault(name.partition(".")[0], {})[name] = (blobs.tell(), len(blob), is_pkg, path, mtime, size)
            blobs.write(blob)
    # serialise per-top indexes, then the top table that points at them (offsets relative to index start)
    idx_parts = []
    top_table: dict[str, tuple[int, int]] = {}
    pos = 0
    for top, entries in sorted(per_top.items()):
        part = marshal.dumps(entries)
        top_table[top] = (pos, len(part))
        idx_parts.append(part)
        pos += len(part)
    top_bytes = marshal.dumps(top_table)
    with open(out, "wb") as f:
        f.write(_HEADER.pack(MAGIC, CODECS.index(codec), len(top_bytes), pos))
        f.write(top_bytes)
        for part in idx_parts:
            f.write(part)
        f.write(blobs.getvalue())
    return {
        "modules": len(seen) - skipped,
        "skipped": skipped,
        "raw_bytes": raw_total,
        "blob_bytes": blobs.tell(),
        "top_table_bytes": len(top_bytes),
        "index_bytes": pos,
        "tops": len(top_table),
    }


class _ResourceLoaderShim:
    """What importlib.resources.readers.FileReader wants: an object with a .path to the module file."""

    def __init__(self, path: str):
        self.path = path


class ArchiveLoader(importlib.abc.InspectLoader):
    def __init__(self, finder: ArchiveFinder):
        self._finder = finder

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(self.get_code(module.__name__), module.__dict__)

    def get_code(self, fullname):
        f = self._finder
        offset, size = f.entry(fullname)[:2]
        start = f.data_start + offset
        return marshal.loads(f.decompress(f.mm[start : start + size]))

    def is_package(self, fullname):
        return self._finder.entry(fullname)[2]

    def get_filename(self, fullname):
        return self._finder.entry(fullname)[3]

    def get_source(self, fullname):
        with open(self.get_filename(fullname), encoding="utf-8") as fh:
            return fh.read()

    def get_data(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def get_resource_reader(self, fullname):
        from importlib.resources.readers import FileReader

        return FileReader(_ResourceLoaderShim(self.get_filename(fullname)))


class ArchiveFinder(importlib.abc.MetaPathFinder):
    def __init__(self, path: str, check_source: bool = True):
        self.check_source = check_source
        self._fh = open(path, "rb")
        self.mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        magic, codec_id, top_len, idx_len = _HEADER.unpack_from(self.mm, 0)
        if magic != MAGIC:
            raise ValueError(f"{path}: not a bytecode archive")
        self.decompress = _decompressor(CODECS[codec_id])
        self._top: dict[str, tuple[int, int]] = marshal.loads(self.mm[_HEADER.size : _HEADER.size + top_len])
        self._index_start = _HEADER.size + top_len
        self.data_start = self._index_start + idx_len
        self._loaded: dict[str, dict] = {}
        self._loader = ArchiveLoader(self)
        self.served = 0
        self.stale = 0

    def entry(self, fullname: str):
        top = fullname.partition(".")[0]
        idx = self._loaded.get(top)
        if idx is None:
            loc = self._top.get(top)
            if loc is None:
                return None
            start = self._index_start + loc[0]
            idx = self._loaded[top] = marshal.loads(self.mm[start : start + loc[1]])
        return idx.get(fullname)

    def find_spec(self, fullname, path=None, target=None):
        e = self.entry(fullname)
        if e is None:
            return None
        origin = e[3]
        if self.check_source:
            try:
                st = os.stat(origin)
            except OSError:
                return None
            if st.st_mtime_ns != e[4] or st.st_size != e[5]:
                self.stale += 1
                return None
        spec = importlib.util.spec_from_loader(fullname, self._loader, origin=origin, is_package=e[2])
        spec.has_location = True
        if e[2]:
            spec.submodule_search_locations = [os.path.dirname(origin)]
        self.served += 1
        return spec


def install(path: str, check_source: bool | None = None) -> ArchiveFinder:
    if check_source is None:
        check_source = os.environ.get("POSTHOG_BYTECODE_ARCHIVE_UNCHECKED") != "1"
    finder = ArchiveFinder(path, check_source=check_source)
    sys.meta_path.insert(0, finder)
    return finder


def default_roots(site: bool = False, stdlib: bool = False, repo: str | None = None) -> list[tuple[str, str]]:
    import sysconfig

    repo = repo or os.getcwd()
    roots = [
        (os.path.join(repo, "posthog"), "posthog"),
        (os.path.join(repo, "ee"), "ee"),
        (os.path.join(repo, "products"), "products"),
        (os.path.join(repo, "common"), "common"),
        (os.path.join(repo, "common/hogvm"), "hogvm"),
        (os.path.join(repo, "common/migration_utils"), "migration_utils"),
    ]
    if site:
        roots += [(p, "") for p in sys.path if p.endswith("site-packages") or "/packages/" in p or "/tools/" in p]
    if stdlib:
        roots.append((sysconfig.get_paths()["stdlib"], ""))
    return roots


def _main(argv: list[str]) -> int:
    import time
    import argparse

    p = argparse.ArgumentParser(prog="bytecode_archive")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", required=True)
    b.add_argument("--codec", choices=CODECS, default="lz4")
    b.add_argument("--site", action="store_true", help="include site-packages and .pth roots")
    b.add_argument("--stdlib", action="store_true", help="include the standard library")
    a = p.parse_args(argv)
    t = time.perf_counter()
    s = build(default_roots(site=a.site, stdlib=a.stdlib), a.out, a.codec)
    print(  # noqa: T201
        f"{a.out}: {s['modules']} modules ({s['skipped']} unparsable skipped) in {s['tops']} top-level names; "
        f"bytecode {s['raw_bytes'] >> 20} MB -> {s['blob_bytes'] >> 20} MB; top table {s['top_table_bytes'] >> 10} KB, "
        f"indexes {s['index_bytes'] >> 20} MB; file {os.path.getsize(a.out) >> 20} MB; {time.perf_counter() - t:.1f}s"
    )
    return 0
