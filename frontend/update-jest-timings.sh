#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="$SCRIPT_DIR/jest-timings.json"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

if [ -n "${1:-}" ]; then
    RUN_ID="$1"
    echo "Using run $RUN_ID..."
else
    echo "Finding latest successful hourly Frontend CI run on master..."
    RUN_ID=$(gh api "repos/{owner}/{repo}/actions/workflows/ci-frontend.yml/runs?status=success&branch=master&event=schedule&per_page=1" \
        --jq '.workflow_runs[0].id')

    if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "null" ]; then
        echo "ERROR: No successful hourly master run found" >&2
        exit 1
    fi
    echo "Found run $RUN_ID"
fi

echo "Downloading JUnit artifacts..."
ARTIFACT_NAMES=$(gh api "repos/{owner}/{repo}/actions/runs/$RUN_ID/artifacts" \
    --jq '.artifacts[] | select(.name | test("^junit-results-frontend-app-[0-9]+$")) | .name')

if [ -z "$ARTIFACT_NAMES" ]; then
    echo "ERROR: No jest JUnit artifacts found for run $RUN_ID" >&2
    exit 1
fi

while IFS= read -r name; do
    gh run download "$RUN_ID" -n "$name" -D "$TMPDIR/$name"
done <<< "$ARTIFACT_NAMES"

echo "Extracting timings from JUnit XML..."
python3 - "$TMPDIR" "$OUTPUT" <<'PY'
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

tmpdir = Path(sys.argv[1])
output = Path(sys.argv[2])
timings: dict[str, float] = {}

for xml_file in sorted(tmpdir.rglob("junit-*.xml")):
    for suite in ET.parse(xml_file).getroot().findall(".//testsuite"):
        name = suite.get("name", "")
        if not re.search(r"\.test\.[cm]?[jt]sx?$", name):
            continue
        timings[name] = timings.get(name, 0.0) + float(suite.get("time", 0))

if not timings:
    print("ERROR: No test timings found in JUnit artifacts", file=sys.stderr)
    print('Check that JEST_JUNIT_SUITE_NAME is set to "{filepath}"', file=sys.stderr)
    sys.exit(1)

rounded = {name: int(round(seconds)) for name, seconds in timings.items()}
output.write_text(json.dumps(rounded, sort_keys=True, indent=4) + "\n")
print(f"Wrote {len(timings)} test files to {output.name}")
PY
