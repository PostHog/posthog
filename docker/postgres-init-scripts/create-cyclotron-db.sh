#!/bin/bash

# This script is used to create the cyclotron database.
# It is run when the postgres container is started.

set -e
set -u

echo "Creating database 'cyclotron' if it doesn't exist"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'cyclotron') THEN
            CREATE DATABASE cyclotron;
        END IF;
    END
    \$\$;
    GRANT ALL PRIVILEGES ON DATABASE cyclotron TO $POSTGRES_USER;
EOSQL 