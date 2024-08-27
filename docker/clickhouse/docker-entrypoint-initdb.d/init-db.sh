#!/bin/bash
set -e

apk add python3
wget https://downloads.python.org/pypy/pypy3.10-v7.3.16-linux64.tar.bz2
tar -xjvf pypy3.10-v7.3.16-linux64.tar.bz2
ln -s
cp -r /idl/* /var/lib/clickhouse/format_schemas/
