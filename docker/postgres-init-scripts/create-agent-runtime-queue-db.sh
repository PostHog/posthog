#!/bin/bash

set -e
set -u

echo "Checking if database 'agent_runtime_queue' exists..."
DB_EXISTS=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='agent_runtime_queue'")

if [ -z "$DB_EXISTS" ]; then
    echo "Creating database 'agent_runtime_queue'..."
    psql -U "$POSTGRES_USER" -c "CREATE DATABASE agent_runtime_queue;"
    psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE agent_runtime_queue TO $POSTGRES_USER;"
    echo "Database 'agent_runtime_queue' created successfully"
else
    echo "Database 'agent_runtime_queue' already exists"
fi
