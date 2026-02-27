#!/bin/bash

set -e
set -u

echo "Checking if database 'test_dagster' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='test_dagster'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'test_dagster'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE test_dagster;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE test_dagster TO $POSTGRES_USER;"
    echo "Database 'test_dagster' created successfully"
else
    echo "Database 'test_dagster' already exists"
fi
