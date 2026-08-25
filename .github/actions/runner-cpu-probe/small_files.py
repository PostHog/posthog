"""Time a collectstatic-shaped workload: write many small files, then hash each one."""

import os
import time
import shutil
import hashlib
import pathlib

count = int(os.environ.get("PROBE_SMALL_FILES", "3000"))
directory = pathlib.Path("probe_small_files")
shutil.rmtree(directory, ignore_errors=True)
directory.mkdir()

blob = b"x" * 4096
started = time.perf_counter()
for index in range(count):
    path = directory / f"f{index}"
    path.write_bytes(blob)
    hashlib.sha256(path.read_bytes()).hexdigest()
elapsed = time.perf_counter() - started

shutil.rmtree(directory, ignore_errors=True)
print(f"{elapsed:.3f}")
