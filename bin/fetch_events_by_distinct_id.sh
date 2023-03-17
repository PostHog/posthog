#!/usr/bin/env bash

# This script is useful if you want to fetch all events for a given distinct_id
# from the events_plugin_ingestion Kafka topic. You may want to do this if you
# are debugging cases where events are missing from the PostHog app, and you are
# trying to track down where they may have been lost. Some PostHog clients don't
# give good visibility into if events were successfully POST'd to the events
# capture endpoints.
#
# The script takes a distinct_id, the token used to ingest the events, a
# start and max message from which we will resolve to a pair of Kafka offsets,
# and a broker list to connect to Kafka with, and the Kafka security protocol
# which defaults to PLAINTEXT.
#
# The script will then fetch all events within the offset range for the given
# token and distinct_id, filtering on the token and distinct_id appearing in the
# Kafka message value. We select the partition to pull based on the sha256 hash
# of the string "token:distinct_id", which is how at the time of writing the
# capture endpoints partition events. Matching events are output to stdout.
#
# We use [kcat](https://github.com/edenhill/kcat) for Kafka operations over the
# Kafka CLI tools, as it is much faster and more reliable. Note that we're using
# kafkacat although rather than the more recent kcat, as the latter is not yet
# available in the Debian package repository.
#
# Script arguments are passed in using the long form, e.g.:
#   ./fetch_events_by_distinct_id.sh --distinct-id=123 --token=abc
#   --start=2021-01-01 --max-messages=100 --brokers=kafka:9092
#   --consumer-property security.protocol=SSL_PLAINTEXT
#

set -euxo pipefail

# Parse arguments
while test $# -gt 0; do
    case "$1" in
    -h | --help)
        echo "USAGE:"
        echo "    ./fetch_events_by_distinct_id.sh [FLAGS]"
        echo " "
        echo "FLAGS:"
        echo "    -h, --help           Print this help information."
        echo "    --distinct-id        The distinct-id to fetch events for."
        echo "    --token              The token used to ingest the events."
        echo "    --start              The start timestamp to fetch events from."
        echo "    --max-messages       The maximum number of messages to fetch."
        echo "    --brokers            The broker list to connect to Kafka with."
        echo "    --consumer-property security.protocol  The security protocol to use when connecting to Kafka. Defaults to PLAINTEXT."
        exit 0
        ;;
    --distinct-id)
        shift
        if test $# -gt 0; then
            export DISTINCT_ID=$1
        else
            echo "ERROR: --distinct-id requires a non-empty option argument."
            exit 1
        fi
        shift
        ;;
    --distinct-id=*)
        export DISTINCT_ID=$(echo $1 | sed -e 's/^[^=]*=//g')
        shift
        ;;
    --token)
        shift
        if test $# -gt 0; then
            export TOKEN=$1
        else
            echo "ERROR: --token requires a non-empty option argument."
            exit 1
        fi
        shift
        ;;
    --token=*)
        export TOKEN=$(echo $1 | sed -e 's/^[^=]*=//g')
        shift
        ;;
    --start)
        shift
        if test $# -gt 0; then
            export START=$1
        else
            echo "ERROR: --start requires a non-empty option argument."
            exit 1
        fi
        shift
        ;;
    --start=*)
        export START=$(echo $1 | sed -e 's/^[^=]*=//g')
        shift
        ;;
    --max-messages)
        shift
        if test $# -gt 0; then
            export MAX_MESSAGES=$1
        else
            echo "ERROR: --max-messages requires a non-empty option argument."
            exit 1
        fi
        shift
        ;;
    --max-messages=*)
        export MAX_MESSAGES=$(echo $1 | sed -e 's/^[^=]*=//g')
        shift
        ;;
    --brokers)
        shift
        if test $# -gt 0; then
            export BROKERS=$1
        else
            echo "ERROR: --brokers requires a non-empty option argument."
            exit 1
        fi
        shift
        ;;
    --brokers=*)
        export BROKERS=$(echo $1 | sed -e 's/^[^=]*=//g')
        shift
        ;;
    --security-protocol)
        shift
        if test $# -gt 0; then
            export SECURITY_PROTOCOL=$1
        else
            echo "ERROR: --security-protocol requires a non-empty option argument."
            exit 1
        fi
        shift
        ;;
    --security-protocol=*)
        export SECURITY_PROTOCOL=$(echo $1 | sed -e 's/^[^=]*=//g')
        shift
        ;;
    *)
        break
        ;;
    esac
done

# Validate arguments
if [[ -z ${DISTINCT_ID:-} ]]; then
    echo "ERROR: --distinct-id is required."
    exit 1
fi
if [[ -z ${TOKEN:-} ]]; then
    echo "ERROR: --token is required."
    exit 1
fi
if [[ -z ${START:-} ]]; then
    echo "ERROR: --start is required."
    exit 1
fi
if [[ -z ${MAX_MESSAGES:-} ]]; then
    echo "ERROR: --max-messages is required."
    exit 1
fi
if [[ -z ${BROKERS:-} ]]; then
    echo "ERROR: --brokers is required."
    exit 1
fi
if [[ -z ${SECURITY_PROTOCOL:-} ]]; then
    export SECURITY_PROTOCOL=PLAINTEXT
fi

# Calculate the PARTITION as the sha256 hash of the string "token:distinct_id"
# then take the murmur2 hash of this and mod it by the number of partitions in
# the topic.
# At the time of writing, capture endpoints perform this sha256 hash, and
# kafka-python performs the murmur2 hash and mod, mimicking the behaviour of
# Kafka Java clients. We use the JSON output of kafkacat to get the number of
# partitions in the topic.
# NUMBER_OF_PARTITIONS=$(kafkacat -b "$BROKERS" -L -t "events_plugin_ingestion" -X security.protocol="$SECURITY_PROTOCOL" -J | jq '.topics[].partitions | length')
SHA256_HASH=$(echo -n "$TOKEN:$DISTINCT_ID" | sha256sum | cut -d' ' -f1)
MURMUR2_HASH=$(echo -n "$SHA256_HASH" | python -c 'import sys, struct, murmurhash2; print(murmurhash2.murmurhash2(sys.stdin.read().strip().encode(), 0x9747b28c))')
PARTITION=$((MURMUR2_HASH % NUMBER_OF_PARTITIONS))

# echo "Fetching events for distinct_id $DISTINCT_ID with token $TOKEN from $START for $MAX_MESSAGES messages from partition $PARTITION"

# Resolve start and end timestamps to Kafka offsets, just for the partition we
# calculate as PARTITON above. We use the docker image
# bitnami/kafka:2.8.1-debian-10-r99 for running Kafka commands.
# We need to first convert the timestamp strings to milliseconds since epoch.
START_TIMESTAMP=$(date -d "$START" +%s%3N)

# Fetch events from Kafka the calculated partition starting from the offset
# specified by the variable START_TIMESTAMP and ending at END_TIMESTAMP. We
# filter by distinct_id and token using jq.
kafkacat -b "$BROKERS" -C \
    -t "events_plugin_ingestion" \
    -p "$PARTITION" \
    -o "s@$START_TIMESTAMP" \
    -c "$MAX_MESSAGES" \
    -X security.protocol="$SECURITY_PROTOCOL" |
    jq -c --arg distinct_id "$DISTINCT_ID" --arg token "$TOKEN" \
        'select(.distinct_id == $distinct_id and .token == $token)'
