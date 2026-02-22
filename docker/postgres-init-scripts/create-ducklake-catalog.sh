#!/bin/bash

set -e
set -u

echo "Checking if database 'ducklake' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='ducklake'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'ducklake'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE ducklake;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE ducklake TO $POSTGRES_USER;"
    echo "Database 'ducklake' created successfully"
else
    echo "Database 'ducklake' already exists"
fi
