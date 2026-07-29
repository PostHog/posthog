#!/usr/bin/env bash
set -euo pipefail

# Refresh nodejs-timings.json from the JUnit artifacts of a CI run.
#
# Merges rather than replaces: a shard whose Jest task hit the turbo cache writes no JUnit XML, so
# most runs only cover part of the suite. Entries for files that no longer exist are dropped.
#
# Usage:
#   ./update-nodejs-timings.sh              # uses latest successful master run
#   ./update-nodejs-timings.sh <run-id>     # uses a specific run
#
# Requires: gh CLI (authenticated), python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="$SCRIPT_DIR/nodejs-timings.json"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

if [ -n "${1:-}" ]; then
    RUN_ID="$1"
    echo "Using run $RUN_ID..."
else
    echo "Finding latest successful Node.js CI run on master..."
    RUN_ID=$(gh run list \
        -w ci-nodejs.yml \
        -s completed \
        --json databaseId,conclusion,headBranch \
        -L 20 \
        --jq '[.[] | select(.conclusion == "success" and .headBranch == "master")][0].databaseId')

    if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "null" ]; then
        echo "ERROR: No successful master run found" >&2
        exit 1
    fi
    echo "Found run $RUN_ID"
fi

echo "Downloading JUnit artifacts..."
ARTIFACT_NAMES=$(gh api "repos/{owner}/{repo}/actions/runs/$RUN_ID/artifacts?per_page=100" \
    --jq '.artifacts[] | select(.expired == false) | select(.name | startswith("junit-results-nodejs-")) | .name')

if [ -z "$ARTIFACT_NAMES" ]; then
    echo "ERROR: No live JUnit artifacts found for run $RUN_ID" >&2
    echo "Shards only upload one when their Jest task misses the turbo cache (1-day retention)" >&2
    exit 1
fi

while IFS= read -r name; do
    gh run download "$RUN_ID" -n "$name" -D "$TMPDIR/$name"
done <<< "$ARTIFACT_NAMES"

echo "Merging timings from JUnit XML..."
python3 -c "
import xml.etree.ElementTree as ET
import json
from pathlib import Path

# Jest's own reporter uses a 5s slow-test threshold; below that a file is noise in the packing
# and would only bloat the manifest with hundreds of sub-second unit tests. The sequencer charges
# anything it has no entry for the median known duration.
MIN_SECONDS = 5.0

root = Path('$SCRIPT_DIR')
timings = json.loads((root / 'nodejs-timings.json').read_text()) if (root / 'nodejs-timings.json').exists() else {}
before = len(timings)

observed = {}
for xml_file in sorted(Path('$TMPDIR').rglob('*.xml')):
    for suite in ET.parse(xml_file).getroot().findall('.//testsuite'):
        # JEST_JUNIT_SUITE_NAME='{filepath}' makes the suite name the path relative to nodejs/.
        filepath = suite.get('name', '')
        if filepath.endswith('.test.ts'):
            observed[filepath] = float(suite.get('time', 0))

# A file seen fast enough this run is no longer worth an entry, so drop it rather than keeping a
# stale slow figure that would skew the packing.
for filepath, seconds in observed.items():
    if seconds >= MIN_SECONDS:
        timings[filepath] = round(seconds, 3)
    else:
        timings.pop(filepath, None)

pruned = [f for f in timings if not (root / f).exists()]
for filepath in pruned:
    del timings[filepath]

with open('$OUTPUT', 'w') as f:
    # indent=4 to match nodejs/.prettierrc — the refresh opens a PR that runs \`prettier --check\`.
    json.dump(timings, f, sort_keys=True, indent=4)
    f.write('\n')

print(f'{len(observed)} files observed in this run, {len(pruned)} deleted files pruned')
print(f'Manifest: {before} -> {len(timings)} files ({sum(timings.values()):.0f}s total)')
"
