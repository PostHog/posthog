#!/usr/bin/env bash
# Runs the backend tests of one product as one pytest process: every test file under
# products/<product>/ except the paths in product-tests-owned-elsewhere.txt.
# CI, its quarantine rerun and `hogli test products/<product>/` all call this script.
#
# pytest starts in the product directory because CI's PYTEST_ADDOPTS name paths
# relative to it: --durations-path ../../.test_durations, --junitxml=junit-product.xml
# and --cov=backend.
#
# Usage: run-product-tests.sh PRODUCT_DIRECTORY [PYTEST_OPTION...]
#
# No `set -u`: the bash 3.2 that ships with macOS fails on an empty "${array[@]}".
set -eo pipefail

if [ "$#" -lt 1 ]; then
    echo "usage: $0 PRODUCT_DIRECTORY [PYTEST_OPTION...]" >&2
    exit 2
fi
product=$1
shift
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [ ! -d "$repo_root/products/$product" ]; then
    echo "::error::products/$product does not exist" >&2
    exit 2
fi

# pytest resolves --ignore against the working directory, so pass absolute paths.
ignore_args=()
# `|| [ -n ... ]` keeps a last line that has no newline. read trims leading blanks, and the
# expansion below trims trailing whitespace and a CR, so both readers of the list see the
# same entries (hogli's orphan check strips each line too).
while read -r pattern || [ -n "$pattern" ]; do
    pattern=${pattern%"${pattern##*[![:space:]]}"}
    case "$pattern" in '' | '#'*) continue ;; esac
    # shellcheck disable=SC2086 # the pattern may hold a glob, which must expand here
    for path in "$repo_root"/$pattern; do
        if [ -e "$path" ]; then
            ignore_args+=("--ignore=$path")
        fi
    done
done < "$repo_root/.github/scripts/product-tests-owned-elsewhere.txt"

cd "$repo_root/products/$product"
# A product declares what its tests need outside Python as a backend:test:setup script in its
# package.json. canvas uses it to install the npm packages of its builder.
if grep -q '"backend:test:setup"' package.json 2>/dev/null; then
    npm run --silent backend:test:setup
fi
status=0
pytest -c ../../pytest.ini --rootdir ../.. "${ignore_args[@]}" -v --tb=short "$@" . || status=$?
if [ "$status" -eq 5 ]; then
    echo "No tests collected in products/$product"
    exit 0
fi
exit "$status"
