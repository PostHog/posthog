#!/bin/sh
# Checks a hog-worker that has no hog next to it yet, in the jobs that only build workers:
#   release/check-worker.sh <hog-worker> [<version>]
# With a hog next to it, `HOG_CHECK_INSTALL=1 hog --version` is the check.

set -eu

hello=$("$1" </dev/null | head -n 1)
[ "$(printf '%s' "$hello" | jq -r '.type')" = hello ] || {
    echo "$1 didn't say hello: $hello" >&2
    exit 1
}
[ $# -lt 2 ] || [ "$(printf '%s' "$hello" | jq -r '.version')" = "$2" ] || {
    echo "$1 isn't version $2: $hello" >&2
    exit 1
}
