#!/usr/bin/env bash
# Prints the number of prose words in a PR body file.
# Headings, tables, fenced code blocks, <details> blocks and HTML comments are not prose.
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
    echo "usage: $0 <pr-body.md>" >&2
    exit 2
fi

sed 's/<!--.*-->//g' "$1" |
    awk '
        /^```/ { in_code = !in_code; next }
        /^ *<details>/ { in_details = 1 }
        /^ *<\/details>/ { in_details = 0; next }
        !in_code && !in_details && !/^ *\|/ && !/^#/
    ' |
    wc -w |
    tr -d ' '
