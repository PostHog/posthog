#!/usr/bin/env bash

# This script is useful if you want to fetch all events for a given distinct_id
# from the events_plugin_ingestion Kafka topic. You may want to do this if you
# are debugging cases where events are missing from the PostHog app, and you are
# trying to track down where they may have been lost. Some PostHog clients don't
# give good visibility into if events were successfully POST'd to the events
# capture endpoints.
#
# The script takes a distinct_id, the token used to ingest the events, a
# start and end timestamp from which we will resolve to a pair of Kafka offsets,
# and a broker list to connect to Kafka with.
#
# The script will then fetch all events within the offset range for the given
# token and distinct_id, filtering on the token and distinct_id appearing in the
# Kafka message value. We select the partition to pull based on the sha256 hash
# of the string "token:distinct_id", which is how at the time of writing the
# capture endpoints partition events. Matching events are output to stdout.
#
# Script arguments are passed in using the long form, e.g.:
#   ./fetch_events_by_distinct_id.sh --distinct_id=123 --token=abc
#   --start=2021-01-01 --end=2021-01-02 --brokers=kafka:9092
#

set -euo pipefail

# Parse arguments
while test $# -gt 0; do
    case "$1" in
    -h | --help)
        echo "USAGE:"
        echo "    ./fetch_events_by_distinct_id.sh [FLAGS]"
        echo " "
        echo "FLAGS:"
        echo "    -h, --help           Print this help information."
        echo "    --distinct_id        The distinct_id to fetch events for."
        echo "    --token              The token used to ingest the events."
        echo "    --start              The start timestamp to fetch events from."
        echo "    --end                The end timestamp to fetch events to."
        echo "    --brokers            The broker list to connect to Kafka with."
        exit 0
        ;;
    --distinct_id)
        shift
        if test $# -gt 0; then
            export DISTINCT_ID=$1
        else
            echo "ERROR: --distinct_id requires a non-empty option argument."
            exit 1
        fi
        shift
        ;;
    --distinct_id=*)
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
    --end)
        shift
        if test $# -gt 0; then
            export END=$1
        else
            echo "ERROR: --end requires a non-empty option argument."
            exit 1
        fi
        shift
        ;;
    --end=*)
        export END=$(echo $1 | sed -e 's/^[^=]*=//g')
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
    *)
        break
        ;;
    esac
done

# Validate arguments
if [[ -z ${DISTINCT_ID:-} ]]; then
    echo "ERROR: --distinct_id is required."
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
if [[ -z ${END:-} ]]; then
    echo "ERROR: --end is required."
    exit 1
fi
if [[ -z ${BROKERS:-} ]]; then
    echo "ERROR: --brokers is required."
    exit 1
fi

# Resolve start and end timestamps to Kafka offsets
START_OFFSET=$(docker-compose exec kafka kafka-run-class kafka.tools.GetOffsetShell --broker-list $BROKERS --topic events_plugin_ingestion --time $START --offsets 1 | awk '{print $3}')
END_OFFSET=$(docker-compose exec kafka kafka-run-class kafka.tools.GetOffsetShell --broker-list $BROKERS --topic events_plugin_ingestion --time $END --offsets 1 | awk '{print $3}')

# Fetch events from Kafka
docker-compose exec kafka kafka-console-consumer --bootstrap-server $BROKERS --topic events_plugin_ingestion --from-beginning --max-messages 1000000 --partition $(echo -n "token:$TOKEN distinct_id:$DISTINCT_ID" | sha256sum | cut -d' ' -f1 | cut -c-8 | xxd -r -p | od -An -t u4 | head -n1) --offset $START_OFFSET --max-offset $END_OFFSET | jq -c 'select(.token == env.TOKEN) | select(.distinct_id == env.DISTINCT_ID)'
