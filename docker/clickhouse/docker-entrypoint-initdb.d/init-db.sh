#!/bin/bash
set -e

apk add python3
cp -r /idl/* /var/lib/clickhouse/format_schemas/
