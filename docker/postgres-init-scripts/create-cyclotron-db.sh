#!/bin/bash

set -e
set -u

echo "Checking if database 'cyclotron' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='cyclotron'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'cyclotron'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE cyclotron;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE cyclotron TO $POSTGRES_USER;"
    echo "Database 'cyclotron' created successfully"
else
    echo "Database 'cyclotron' already exists"
fi