#!/bin/bash

# Simple bash script for behavioral cohorts migration
set -e

# Set database name based on environment
if [[ "${NODE_ENV}" == "test" || "${TEST}" == "1" ]]; then
    DB_NAME="test_behavioral_cohorts"
else
    DB_NAME="behavioral_cohorts"
fi

# Use environment variables with defaults
DB_HOST="${POSTGRES_BEHAVIORAL_COHORTS_HOST:-localhost}"
DB_USER="${POSTGRES_BEHAVIORAL_COHORTS_USER:-posthog}"
DB_PASS="${POSTGRES_BEHAVIORAL_COHORTS_PASSWORD:-posthog}"
DB_PORT="5432"

# Get database URL from environment or construct from defaults
BEHAVIORAL_COHORTS_DB_URL="${BEHAVIORAL_COHORTS_DATABASE_URL:-postgres://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}}"

echo "Performing behavioral cohorts migrations"
echo "Database name: ${DB_NAME}"

# Create database if it doesn't exist
if [[ -n "${DB_PASS}" ]]; then
    export PGPASSWORD="${DB_PASS}"
fi
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${DB_NAME}" 2>/dev/null || true

# Run migrations
DATABASE_URL="${BEHAVIORAL_COHORTS_DB_URL}" npx node-pg-migrate up --config-file .node-pg-migrate-behavioral-cohorts.json

echo "Behavioral cohorts migrations completed successfully"