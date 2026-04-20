#!/bin/bash

set -e
set -u

echo "Checking if database 'cyclotron_node' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='cyclotron_node'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'cyclotron_node'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE cyclotron_node;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE cyclotron_node TO $POSTGRES_USER;"
    echo "Database 'cyclotron_node' created successfully"
else
    echo "Database 'cyclotron_node' already exists"
fi
