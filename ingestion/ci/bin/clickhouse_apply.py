# ruff: noqa: T201
"""Apply a file of ClickHouse statements, one request each, to the test database over HTTP."""

import sys
import urllib.parse
import urllib.request
from pathlib import Path

url = "http://localhost:8123/?" + urllib.parse.urlencode({"database": "posthog_test"})
text = Path(sys.argv[1]).read_text()
statements = [s.strip() for s in text.split(";\n\n") if s.strip() and not s.strip().startswith("--")]
for statement in statements:
    body = statement.rstrip(";").encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=120) as response:
        response.read()
print(f"applied {len(statements)} statements")
