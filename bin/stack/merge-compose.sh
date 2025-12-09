#!/usr/bin/env bash
set -euo pipefail

# Merge docker-compose files into a single self-contained file
# This resolves all 'extends' directives by using docker-compose config

if [ $# -ne 1 ]; then
  echo "Usage: $0 <source-compose-file>"
  echo "Example: $0 ../../docker-compose.dev-minimal.yml"
  exit 1
fi

source_file="$1"

if [ ! -f "$source_file" ]; then
  echo "Error: File not found: $source_file"
  exit 1
fi

# Get the directory of the source file to use as working directory
source_dir=$(dirname "$source_file")
source_basename=$(basename "$source_file")

# Use docker-compose config to resolve all extends directives
# This merges base.yml into the final output
# Then remove 'build:' sections since we provide pre-built images
cd "$source_dir"
docker-compose -f "$source_basename" config | \
  sed '/^    build:$/,/^    [a-z]/{ /^    build:$/d; /^      /d; }'
