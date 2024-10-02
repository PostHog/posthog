#!/bin/bash
set -e

apt-get update
apt-get -y install python3
wget http://launchpadlibrarian.net/588931980/libc6_2.35-0ubuntu3_amd64.deb
dpkg --auto-deconfigure -i libc6_2.35-0ubuntu3_amd64.deb
cp -r /idl/* /var/lib/clickhouse/format_schemas/
