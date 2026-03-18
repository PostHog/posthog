#!/bin/bash

set -e
set -u

echo "Checking if database 'ducklake_catalog' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='ducklake_catalog'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'ducklake_catalog'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE ducklake_catalog;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE ducklake_catalog TO $POSTGRES_USER;"
    echo "Database 'ducklake_catalog' created successfully"
else
    echo "Database 'ducklake_catalog' already exists"
fi
