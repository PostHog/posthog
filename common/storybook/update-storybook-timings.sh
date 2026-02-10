#!/usr/bin/env bash
set -euo pipefail

# Regenerate storybook-timings.json from the latest successful master CI run.
#
# Usage: ./update-storybook-timings.sh
#
# Requires: gh CLI authenticated, python3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="$SCRIPT_DIR/storybook-timings.json"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

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

echo "Downloading logs from run $RUN_ID..."
gh-logs-grab download "https://github.com/PostHog/posthog/actions/runs/$RUN_ID" \
    --all -o "$TMPDIR" 2>&1 | tail -3

LOG_DIR=$(find "$TMPDIR" -maxdepth 2 -mindepth 2 -type d | head -1)

echo "Extracting timings..."
python3 -c "
import re, json, sys
from pathlib import Path

logs_dir = Path('$LOG_DIR')
timings = {}
pattern = re.compile(r'(PASS|FAIL) browser: (\w+) \.\./\.\./(.+?) \(([0-9.]+) s\)')

for log_file in logs_dir.glob('Visual_regression_tests_-_*'):
    with open(log_file) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                _, browser, filepath, duration = m.groups()
                if filepath not in timings:
                    timings[filepath] = {}
                timings[filepath][browser] = round(float(duration), 1)

if not timings:
    print('ERROR: No test timings found in logs', file=sys.stderr)
    sys.exit(1)

with open('$OUTPUT', 'w') as f:
    json.dump(timings, f, sort_keys=True, indent=2)
    f.write('\n')

chromium = sum(1 for v in timings.values() if 'chromium' in v)
webkit = sum(1 for v in timings.values() if 'webkit' in v)
print(f'Wrote {len(timings)} test files ({chromium} chromium, {webkit} webkit) to storybook-timings.json')
"
