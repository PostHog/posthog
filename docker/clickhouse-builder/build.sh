#!/bin/bash

# Practical advice: Use this in development only!
#
# This builds an docker image for the M1 Mac, and pretends it's the one we use from Yandex

docker build . -f arm64.compile.Dockerfile -t yandex/clickhouse-server:21.6.5
