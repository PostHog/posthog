import os
import sys
import json
import filecmp
import hashlib
from collections import defaultdict
from pathlib import Path

roots = [Path("/code/staticfiles"), Path("/code/frontend/dist")]
by_size: defaultdict[tuple[int, int, int, int], list[Path]] = defaultdict(list)
for root in roots:
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            s = p.stat()
            by_size[(s.st_size, s.st_mode, s.st_uid, s.st_gid)].append(p)
saved = linked = 0
for (size, *_), paths in by_size.items():
    if len(paths) < 2 or size == 0:
        continue
    by_hash: dict[bytes, Path] = {}
    for p in paths:
        with p.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").digest()
        if digest in by_hash:
            first = by_hash[digest]
            # Hash only selects candidates. Compare every byte before sharing the inode.
            if filecmp.cmp(p, first, shallow=False) and p.stat().st_ino != first.stat().st_ino:
                p.unlink()
                os.link(first, p)
                saved += size
                linked += 1
        else:
            by_hash[digest] = p
sys.stdout.write(json.dumps({"linked": linked, "payload_bytes_saved": saved}) + "\n")
