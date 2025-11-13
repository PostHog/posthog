#!/bin/bash

set -e
set -u

echo "Checking if database 'behavioral_cohorts' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='behavioral_cohorts'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'behavioral_cohorts'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE behavioral_cohorts;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE behavioral_cohorts TO $POSTGRES_USER;"
    echo "Database 'behavioral_cohorts' created successfully"
else
    echo "Database 'behavioral_cohorts' already exists"
fi
