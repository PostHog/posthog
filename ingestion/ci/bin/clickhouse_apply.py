# ruff: noqa: T201
"""Apply a file of ClickHouse statements, one request each, to the test database over HTTP.

A statement that fails because a posthog_test table is missing is skipped, the way
run_clickhouse_statement_in_parallel in posthog/test/base.py skips it for Django's tests.
"""

import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UNKNOWN_TABLE = "60"

url = "http://localhost:8123/?" + urllib.parse.urlencode({"database": "posthog_test"})
text = Path(sys.argv[1]).read_text()
statements = [s.strip() for s in text.split(";\n\n") if s.strip() and not s.strip().startswith("--")]
skipped = 0
for statement in statements:
    body = statement.rstrip(";").encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=120) as response:
            response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        if error.headers.get("X-ClickHouse-Exception-Code") == UNKNOWN_TABLE and "posthog_test" in detail:
            skipped += 1
            continue
        print(f"failed statement:\n{statement}\n{detail}", file=sys.stderr)
        raise SystemExit(1)
print(f"applied {len(statements) - skipped} statements, skipped {skipped} on missing posthog_test tables")
