#!/bin/bash

# Practical advice: Use this in development only!
#
# This builds an docker image for the M1 Mac.
# The build will take about 90min.
# Set the GIT_TAG in arm64.compile.Dockerfile to choose a version.

cd "$(dirname "$0")"

docker build assets -f assets/arm64.compile.Dockerfile -t clickhouse-dev-arm64:latest
