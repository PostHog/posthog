#!/bin/bash

set -e
set -u

echo "Checking if database 'cyclotron_shadow' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='cyclotron_shadow'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'cyclotron_shadow'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE cyclotron_shadow;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE cyclotron_shadow TO $POSTGRES_USER;"
    echo "Database 'cyclotron_shadow' created successfully"
else
    echo "Database 'cyclotron_shadow' already exists"
fi
