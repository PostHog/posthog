#!/bin/sh

set -eu

PRODUCTS_DIR=${PRODUCTS_DIR:-/products}
ROUTING_FILE="$PRODUCTS_DIR/db_routing.yaml"

if [ ! -f "$ROUTING_FILE" ]; then
    echo "Routing file '$ROUTING_FILE' not found; skipping product DB creation"
    exit 0
fi

# Extract unique database names from db_routing.yaml
# Use POSIX character class — \s is not portable across awk implementations (e.g. BusyBox)
awk -F': ' '/^[[:space:]]*database:/{print $2}' "$ROUTING_FILE" | tr -d '"' | tr -d "'" | sort -u | while read -r db_name; do
    [ -n "$db_name" ] || continue

    # Validate: only alphanumeric and underscores
    case "$db_name" in
        *[!a-z0-9_]*) echo "Skipping invalid database name: '$db_name'"; continue ;;
    esac

    local_db_name="posthog_${db_name}"

    echo "Checking if database '$local_db_name' exists..."
    db_exists=$(psql -U "$POSTGRES_USER" -tAc "SELECT 1 FROM pg_database WHERE datname='${local_db_name}'")

    if [ -z "$db_exists" ]; then
        echo "Creating database '$local_db_name'..."
        psql -U "$POSTGRES_USER" -c "CREATE DATABASE ${local_db_name};"
        psql -U "$POSTGRES_USER" -c "GRANT ALL PRIVILEGES ON DATABASE ${local_db_name} TO $POSTGRES_USER;"
        echo "Database '$local_db_name' created successfully"
    else
        echo "Database '$local_db_name' already exists"
    fi
done
