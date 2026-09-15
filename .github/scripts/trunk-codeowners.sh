#!/usr/bin/env bash
# Write the owners.yaml map into a CODEOWNERS file Trunk can read, and point the uploader at it
# through GITHUB_ENV. Trunk attributes a flaky test to a team by matching the JUnit file attribute
# against a CODEOWNERS file, and .github/CODEOWNERS covers only the paths that need a blocking
# approval, so without this almost every test reaches Trunk unowned.
#
# Best effort by design. Every uploading job runs this, and not all of them have a Python
# environment. On any failure the uploader falls back to .github/CODEOWNERS, which is what it read
# before this existed, so a failed generation costs attribution and never a red check.
set -uo pipefail

output_dir="${1:-}"
if [ -z "$output_dir" ]; then
    echo "usage: $0 OUTPUT_DIR" >&2
    exit 0
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# The file has to carry this name: the uploader takes a directory and looks for CODEOWNERS in it.
target="$output_dir/CODEOWNERS"

generate() {
    # uv first, because CI images carry uv more often than a python with pyyaml, and --no-project
    # keeps it off this repo's own dependency sync. The entrypoint needs stdlib plus pyyaml only.
    if command -v uv >/dev/null 2>&1; then
        uv run --no-project --with pyyaml python -m posthog_owners --codeowners "$target" && return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 -m posthog_owners --codeowners "$target" && return 0
    fi
    return 1
}

fall_back() {
    echo "::notice::$1; Trunk falls back to .github/CODEOWNERS for test ownership"
    exit 0
}

mkdir -p "$output_dir" || fall_back "Could not create $output_dir"

if ! PYTHONPATH="$repo_root/tools/owners" generate >/dev/null 2>&1; then
    fall_back "Could not generate the Trunk ownership map"
fi

rule_count="$(grep -cvE '^#|^$' "$target" 2>/dev/null || true)"
if [ "${rule_count:-0}" -lt 1 ]; then
    fall_back "The generated Trunk ownership map has no rules"
fi

{
    echo "TRUNK_CODEOWNERS_PATH=$output_dir"
    # Without this the uploader tries the GitLab parser first and only falls back to GitHub's.
    echo "TRUNK_CODEOWNERS_TYPE=github"
} >>"${GITHUB_ENV:-/dev/null}"

echo "Trunk ownership map: $rule_count rule(s) from the owners.yaml tree"
