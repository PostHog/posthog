#!/bin/sh

set -eu

PRODUCTS_DIR=${PRODUCTS_DIR:-/products}
ROUTING_FILE="$PRODUCTS_DIR/db_routing.yaml"

if [ ! -f "$ROUTING_FILE" ]; then
    echo "Routing file '$ROUTING_FILE' not found; skipping product DB creation"
    exit 0
fi

awk -F': ' '/^\s*database:/{print $2}' "$ROUTING_FILE" | tr -d '"' | tr -d "'" | while read -r db_alias; do
    [ -n "$db_alias" ] || continue

    alias_without_suffix=${db_alias%_db_writer}
    alias_without_suffix=${alias_without_suffix%_writer}
    db_name="posthog_${alias_without_suffix}"

    echo "Checking if database '$db_name' exists..."
    db_exists=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='${db_name}'")

    if [ -z "$db_exists" ]; then
        echo "Creating database '$db_name'..."
        psql -U "$POSTGRES_USER" -c "CREATE DATABASE ${db_name};"
        psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE ${db_name} TO $POSTGRES_USER;"
        echo "Database '$db_name' created successfully"
    else
        echo "Database '$db_name' already exists"
    fi
done
