#!/bin/bash
# Extract Depot build ID from GitHub Actions workflow run logs
#
# Usage:
#   ./extract_depot_build_id.sh <run_id>
#   ./extract_depot_build_id.sh 18507640352

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <run_id>" >&2
    exit 1
fi

RUN_ID="$1"

# Fetch logs and extract Depot build ID
gh run view "$RUN_ID" --log | \
    grep -oE 'https://depot\.dev/orgs/[a-z0-9]+/projects/[a-z0-9]+/builds/([a-z0-9]{10})' | \
    grep -oE 'builds/[a-z0-9]{10}' | \
    sed 's/builds\///' | \
    head -1
