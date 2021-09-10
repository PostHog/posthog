#!/bin/bash

# Practical advice: Use this in development only!
#
# This builds an docker image for the M1 Mac.
# The build will take about 90min.
# The Clickhouse version you're getting is: 21.9.2.17
#
# Related issue you'll run into: https://github.com/PostHog/posthog/issues/5684
# Just uncomment "SAMPLE BY uuid" in ee/clickhouse/sql/events.py:38

cd "$(dirname "$0")"

docker build assets -f assets/arm64.compile.Dockerfile -t clickhouse-dev-arm64:latest
