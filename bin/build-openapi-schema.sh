#!/usr/bin/env bash
# Generate OpenAPI schema from Django backend
# Usage: ./bin/build-openapi-schema.sh

set -e

SCHEMA_PATH="frontend/src/types/api/openapi.json"
mkdir -p "$(dirname "$SCHEMA_PATH")"

python manage.py spectacular --file "$SCHEMA_PATH" --format openapi-json

echo "OpenAPI schema written to $SCHEMA_PATH"
