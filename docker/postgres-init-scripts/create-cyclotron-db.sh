#!/bin/bash

# This script is used to create the cyclotron database.
# It is run when the postgres container is started.

set -e
set -u

echo "Creating database 'cyclotron'"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE cyclotron;
    GRANT ALL PRIVILEGES ON DATABASE cyclotron TO $POSTGRES_USER;
EOSQL 