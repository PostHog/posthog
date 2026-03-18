#!/usr/bin/env bash
set -euo pipefail

# Regenerate storybook-timings.json from JUnit artifacts of a CI run.
#
# Usage:
#   ./update-storybook-timings.sh              # uses latest successful master run
#   ./update-storybook-timings.sh <run-id>     # uses a specific run
#
# Requires: gh CLI (authenticated), python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="$SCRIPT_DIR/storybook-timings.json"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

if [ -n "${1:-}" ]; then
    RUN_ID="$1"
    echo "Using run $RUN_ID..."
else
    echo "Finding latest successful storybook CI run on master..."
    RUN_ID=$(gh run list \
        -w ci-storybook.yml \
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
ARTIFACT_NAMES=$(gh api "repos/{owner}/{repo}/actions/runs/$RUN_ID/artifacts" \
    --jq '.artifacts[] | select(.name | startswith("junit-results-storybook-")) | .name')

if [ -z "$ARTIFACT_NAMES" ]; then
    echo "ERROR: No JUnit artifacts found for run $RUN_ID" >&2
    echo "Make sure the run used --junit and has JEST_JUNIT_SUITE_NAME='{filepath}'" >&2
    exit 1
fi

while IFS= read -r name; do
    gh run download "$RUN_ID" -n "$name" -D "$TMPDIR/$name"
done <<< "$ARTIFACT_NAMES"

echo "Extracting timings from JUnit XML..."
python3 -c "
import xml.etree.ElementTree as ET
import json, sys, re
from pathlib import Path

tmpdir = Path('$TMPDIR')
timings = {}

for xml_file in sorted(tmpdir.rglob('junit.xml')):
    # Artifact dir name: junit-results-storybook-{browser}-{shard}
    browser = xml_file.parent.name.split('storybook-')[1].rsplit('-', 1)[0]

    tree = ET.parse(xml_file)
    for suite in tree.getroot().findall('.//testsuite'):
        name = suite.get('name', '')
        time_s = float(suite.get('time', 0))

        # Paths are relative from common/storybook/, e.g. ../../frontend/src/...
        filepath = re.sub(r'^(\.\./)+', '', name)
        if not filepath.endswith('.stories.tsx'):
            continue

        if filepath not in timings:
            timings[filepath] = {}
        timings[filepath][browser] = round(time_s, 1)

if not timings:
    print('ERROR: No test timings found in JUnit artifacts', file=sys.stderr)
    print('Check that JEST_JUNIT_SUITE_NAME is set to \"{filepath}\"', file=sys.stderr)
    sys.exit(1)

with open('$OUTPUT', 'w') as f:
    json.dump(timings, f, sort_keys=True, indent=2)
    f.write('\n')

chromium = sum(1 for v in timings.values() if 'chromium' in v)
webkit = sum(1 for v in timings.values() if 'webkit' in v)
print(f'Wrote {len(timings)} test files ({chromium} chromium, {webkit} webkit) to storybook-timings.json')
"
