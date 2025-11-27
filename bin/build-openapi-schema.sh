#!/usr/bin/env bash
# Generate OpenAPI schema from Django backend
# Usage: ./bin/build-openapi-schema.sh

set -e

SCHEMA_PATH="frontend/src/types/api/openapi.json"
mkdir -p "$(dirname "$SCHEMA_PATH")"

# Include internal endpoints - these are used by the frontend
OPENAPI_INCLUDE_INTERNAL=1 python manage.py spectacular --file "$SCHEMA_PATH" --format openapi-json

echo "OpenAPI schema written to $SCHEMA_PATH"
