#!/bin/bash
set -e

apt-get update
# Necessary because clickhouse runs on Ubuntu 20, which has an old glibc and an old python default
# Can remove when we upgrade clickhouse, as the new images run on Ubuntu 22
apt-get -y install python3.9
ln -s /usr/bin/python3.9 /usr/bin/python3
wget http://launchpadlibrarian.net/588931980/libc6_2.35-0ubuntu3_amd64.deb
dpkg --auto-deconfigure -i libc6_2.35-0ubuntu3_amd64.deb
cp -r /idl/* /var/lib/clickhouse/format_schemas/
