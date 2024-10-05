#!/bin/bash
set -e

apt-get update
apt-get -y install python3.9
ln -s /usr/bin/python3.9 /usr/bin/python3
cp -r /idl/* /var/lib/clickhouse/format_schemas/
