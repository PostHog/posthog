# ruff: noqa: T201
"""Apply a file of ClickHouse statements, one request each, to the test database over HTTP."""

import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

url = "http://localhost:8123/?" + urllib.parse.urlencode({"database": "posthog_test"})
text = Path(sys.argv[1]).read_text()
# Comment lines are dropped, not the statements they precede.
statements = [re.sub(r"^\s*--.*\n", "", s, flags=re.M).strip() for s in text.split(";\n\n")]
statements = [s for s in statements if s]
for statement in statements:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=statement.rstrip(";").encode()), timeout=120
        ) as response:
            response.read()
    except urllib.error.HTTPError as error:
        print(f"failed statement:\n{statement}\n{error.read().decode(errors='replace')}", file=sys.stderr)
        raise SystemExit(1)
print(f"applied {len(statements)} statements")
