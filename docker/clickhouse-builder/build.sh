#!/bin/bash

# Practical advice: Use this in development only!
#
# This builds an docker image for the M1 Mac, and pretends it's the one we use from Yandex.
# The build will take about 90min.
#
# The image is published with the version: 21.6.5
# The Clickhouse version you're actually getting is: 21.9.2.17
#
# Related issue you'll run into: https://github.com/PostHog/posthog/issues/5684
# Just uncomment "SAMPLE BY uuid" in ee/clickhouse/sql/events.py:38

docker build assets -f assets/arm64.compile.Dockerfile -t yandex/clickhouse-server:21.6.5
