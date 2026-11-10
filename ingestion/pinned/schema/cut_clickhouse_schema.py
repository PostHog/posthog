# ruff: noqa: T201
"""Cut the ClickHouse statements to the objects the Node packages name and what those depend on.

An object is kept when the packages name it, when it is a materialized view writing to a kept object,
or when a kept statement names it. Statements keep their order, so dependencies are created first.
"""

import re
import sys
from pathlib import Path

statements = [s.strip() for s in Path(sys.argv[1]).read_text().split(";\n\n") if s.strip()]
identifiers = set(Path(sys.argv[2]).read_text().split())

CREATE = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(MATERIALIZED\s+VIEW|VIEW|TABLE|DICTIONARY)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:`?\w+`?\.)?`?(\w+)`?",
    re.I | re.M,
)
TO_TARGET = re.compile(r"\bTO\s+(?:`?\w+`?\.)?`?(\w+)`?", re.I)
WORD = re.compile(r"\b\w+\b")

# An object can be created more than once (IF NOT EXISTS, OR REPLACE); its statements are kept together
# and replayed in setup order, so the result matches what setup_test_environment builds.
named: list[tuple[str, str]] = []
objects: dict[str, str] = {}
kinds: dict[str, str] = {}
for statement in statements:
    m = CREATE.search(statement)
    if not m:
        raise SystemExit(f"not a CREATE statement:\n{statement[:200]}")
    name = m.group(2)
    named.append((name, statement))
    objects[name] = objects.get(name, "") + "\n" + statement
    kinds[name] = re.sub(r"\s+", " ", m.group(1).upper())

keep = {name for name in objects if name in identifiers}
while True:
    added = set()
    for name, statement in objects.items():
        if name in keep:
            added |= (set(WORD.findall(statement)) & objects.keys()) - keep
        elif kinds[name] == "MATERIALIZED VIEW":
            target = TO_TARGET.search(statement)
            if target and target.group(1) in keep:
                added.add(name)
    if not added:
        break
    keep |= added

print("-- The ClickHouse objects the Node packages reach, cut from the schema setup_test_environment creates.")
print("-- Refresh with ingestion/pinned/schema/refresh (see SOURCE.json for the source commit).\n")
print(";\n\n".join(statement for name, statement in named if name in keep) + ";")
