#!/bin/bash
set -e

apt-get update
apt-get -y install python3.9

# Check if /usr/bin/python3 already exists and if it points to python3.9
if [[ $(readlink /usr/bin/python3) != "/usr/bin/python3.9" ]]; then
    ln -sf /usr/bin/python3.9 /usr/bin/python3
fi

cp -r /idl/* /var/lib/clickhouse/format_schemas/

# flush all log tables to ensure they are created
clickhouse client --query "system flush logs"