#!/bin/bash
set -e

apt-get update
apt-get -y install python3.9

# Check if /usr/bin/python3 already exists and if it points to python3.9
if [[ $(readlink /usr/bin/python3) != "/usr/bin/python3.9" ]]; then
    ln -sf /usr/bin/python3.9 /usr/bin/python3
fi

cp -r /idl/* /var/lib/clickhouse/format_schemas/

# Wait for ClickHouse to be ready to accept queries, then flush log tables to ensure
# system log tables (e.g., system.crash_log) are created. Use timeout to avoid hanging.
READY=false
for i in {1..30}; do
    if clickhouse client --query "select 1" > /dev/null 2>&1; then
        clickhouse client --query "system flush logs"
        READY=true
        break
    fi
    sleep 1
done

if [ "$READY" = false ]; then
    echo "ClickHouse failed to become ready after 30 seconds" >&2
    exit 1
fi