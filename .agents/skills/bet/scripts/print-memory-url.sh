#!/usr/bin/env bash
# Print the tokened https clone URL for a product's memory repo — used to
# fill in a managed bet's memory_repo_url *before* creating the bet (funding
# needs it up front; memory-seed.sh only pushes the branch after).
#
# Usage: print-memory-url.sh [product]   (default product: foundry, or $MEMORY_GIT_PRODUCT)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

PRODUCT="${1:-${MEMORY_GIT_PRODUCT:-foundry}}"

if ! memory_available; then
    echo "ERROR: ${MEMORY_ENV} not found or incomplete — cannot build a memory_repo_url without it." >&2
    exit 1
fi

memory_repo_url "$PRODUCT"
