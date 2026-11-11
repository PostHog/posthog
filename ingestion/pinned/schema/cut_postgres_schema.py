# ruff: noqa: T201
"""Cut a pg_dump schema down to the listed tables, their sequences, indexes and the constraints between them."""

import re
import sys
from pathlib import Path

sql = Path(sys.argv[1]).read_text()
keep = set(Path(sys.argv[2]).read_text().split())
blocks = re.split(r"\n\n+", sql)
out: list[str] = []
sequences: list[tuple[str, str]] = []
owned: dict[str, str] = {}
for block in blocks:
    s = block.strip()
    if not s or s.startswith("--") or s.startswith("SET ") or s.startswith("SELECT pg_catalog.set_config"):
        continue
    if s.startswith(("CREATE EXTENSION", "COMMENT ON EXTENSION", "CREATE TYPE", "CREATE FUNCTION", "CREATE SCHEMA")):
        out.append(s)
        continue
    if m := re.match(r'CREATE SEQUENCE public\.("?[a-z0-9_]+"?)', s):
        sequences.append((m.group(1).strip('"'), s))
        continue
    if m := re.match(r'ALTER SEQUENCE public\.("?[a-z0-9_]+"?) OWNED BY public\.("?[a-z0-9_]+"?)\.', s):
        owned[m.group(1).strip('"')] = m.group(2).strip('"')
        name = m.group(2)
    elif m := re.match(r'CREATE TABLE public\.("?[a-z0-9_]+"?) \(', s):
        name = m.group(1)
    elif m := re.match(r'ALTER TABLE (?:ONLY )?public\.("?[a-z0-9_]+"?)', s):
        name = m.group(1)
    elif m := re.match(r'CREATE (?:UNIQUE )?INDEX \S+ ON public\.("?[a-z0-9_]+"?)', s):
        name = m.group(1)
    else:
        continue
    if name.strip('"') not in keep:
        continue
    fk = re.search(r'REFERENCES public\.("?[a-z0-9_]+"?)', s)
    if fk and fk.group(1).strip('"') not in keep:
        continue
    out.append(s)
kept_sequences = [s for seq, s in sequences if owned.get(seq) in keep or any(seq.startswith(t + "_") for t in keep)]
print("-- Django tables the ingestion Node code and the hog engine read, cut from the migrated-schema dump.")
print("-- Refresh with ingestion/pinned/schema/refresh (see SOURCE.json for the source commit).\n")
print("\n\n".join(kept_sequences + out))
