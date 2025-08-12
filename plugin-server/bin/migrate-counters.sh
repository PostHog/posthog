#!/bin/bash

# Simple bash script for counters migration
set -e

# Set database name based on environment
if [[ "${NODE_ENV}" == "test" || "${TEST}" == "1" ]]; then
    DB_NAME="test_counters"
else
    DB_NAME="counters"
fi

# Use environment variables with defaults
DB_HOST="${POSTGRES_COUNTERS_HOST:-localhost}"
DB_USER="${POSTGRES_COUNTERS_USER:-posthog}"
DB_PASS="${POSTGRES_COUNTERS_PASSWORD:-posthog}"
DB_PORT="5432"

# Get database URL from environment or construct from defaults
COUNTERS_DB_URL="${COUNTERS_DATABASE_URL:-postgres://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}}"

echo "Performing counters migrations"
echo "Database name: ${DB_NAME}"

# Create database if it doesn't exist
if [[ -n "${DB_PASS}" ]]; then
    export PGPASSWORD="${DB_PASS}"
fi
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${DB_NAME}" 2>/dev/null || true

# Run migrations
DATABASE_URL="${COUNTERS_DB_URL}" npx node-pg-migrate up --migrations-dir src/migrations

echo "Counters migrations completed successfully"