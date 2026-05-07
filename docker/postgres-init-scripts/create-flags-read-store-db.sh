#!/bin/bash

set -e
set -u

echo "Checking if database 'flags_read_store' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='flags_read_store'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'flags_read_store'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE flags_read_store;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE flags_read_store TO $POSTGRES_USER;"
    echo "Database 'flags_read_store' created successfully"
else
    echo "Database 'flags_read_store' already exists"
fi
