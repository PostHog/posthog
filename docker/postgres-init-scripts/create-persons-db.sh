#!/bin/bash

set -e
set -u

echo "Checking if database 'posthog_persons' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='posthog_persons'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'posthog_persons'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE posthog_persons;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE posthog_persons TO $POSTGRES_USER;"
    echo "Database 'posthog_persons' created successfully"
else
    echo "Database 'posthog_persons' already exists"
fi
