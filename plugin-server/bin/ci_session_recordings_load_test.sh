#!/usr/bin/env bash

# This script is used to load test the session recordings ingestion pipeline in
# CI. It is not intended to provide a realistic load test, but rather to provide
# some basic method to see if performance is affected in an obvious way by code
# changes.
#
# The script first sets up the database to be ready to ingest by running the
# `setup_dev` management command, which will create a team with a token
# `e2e_token_1239`, then it will start the plugin server with only the session
# recordings consumer running. It will then generate example session recording
# events via the `generate_session_recordings_messages.py` script and send them
# to the `session_recording_events` topic in Kafka. We then wait for the
# ingestion lag to drop to zero and record the time between loading the events
# into Kafka and the ingestion lag dropping to zero.
#
# To ensure we can debug any issues with the plugin-server, we redirect the
# output to a file and print this in a GitHub actions block at the end.

set -euo pipefail

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# The number of sessions to generate and ingest, defaulting to 10 if not already
# set.
SESSONS_COUNT=${SESSONS_COUNT:-10}
TOKEN=e2e_token_1239  # Created by the setup_dev management command.

SESSION_RECORDING_EVENTS_TOPIC=session_recording_events
SESSION_RECORDING_INGESTION_CONSUMER_GROUP=session-recordings

# Before we do anything, reset the consumer group offsets to the latest offsets.
# This is to ensure that we are only testing the ingestion of new messages, and
# not the replay of old messages.
echo "Resetting consumer group offsets to latest"
docker compose \
    -f $DIR/../../docker-compose.dev.yml exec \
    -T kafka kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 \
    --reset-offsets \
    --to-latest \
    --group $SESSION_RECORDING_INGESTION_CONSUMER_GROUP \
    --topic $SESSION_RECORDING_EVENTS_TOPIC \
    --execute

$DIR/../../manage.py setup_dev || true  # Assume a failure means it has already been run.

# Start the plugin server with only the session recordings consumer running. We
# need to make sure that we terminate the backgrounded process on exit, so we
# use the `trap` command to kill all backgrounded processes when the last one
# terminates.
trap 'kill $(jobs -p)' EXIT
PLUGIN_SERVER_MODE=recordings-ingestion pnpm start:dev &> /tmp/plugin-server.log &

# Wait for the plugin server health check to be ready, and timeout after 30
# seconds with exit code 1.
SECONDS=0

while [[ $SECONDS -lt 30 ]]; do
    if curl -sSf http://localhost:6738/_health > /dev/null; then
        break
    fi
    sleep 1
done

if [[ $SECONDS -ge 30 ]]; then
    echo "Timed out waiting for plugin server health check to be ready"
    exit 1
fi

# Generate the session recording events and send them to Kafka.
echo "Generating $SESSONS_COUNT session recording events"
$DIR/generate_session_recordings_messages.py \
        --count $SESSONS_COUNT \
        --token $TOKEN | \
    docker compose \
        -f $DIR/../../docker-compose.dev.yml exec \
        -T kafka kafka-console-producer.sh \
        --topic $SESSION_RECORDING_EVENTS_TOPIC \
        --broker-list localhost:9092

# Wait for the ingestion lag for the session recordings consumer group for the
# session recording events topic to drop to zero, timing out after 120 seconds
# with exit code 1. We also print progress of the lag every second.
SECONDS=0

while [[ $SECONDS -lt 120 ]]; do
    LAG=$(docker compose \
        -f $DIR/../../docker-compose.dev.yml exec \
        -T kafka kafka-consumer-groups.sh \
        --bootstrap-server localhost:9092 \
        --describe \
        --group $SESSION_RECORDING_INGESTION_CONSUMER_GROUP \
        | grep $SESSION_RECORDING_EVENTS_TOPIC \
        | awk '{print $5}')

    echo "Ingestion lag: $LAG"

    if [[ $LAG -eq 0 ]]; then
        break
    fi

    sleep 1
done

if [[ $SECONDS -ge 120 ]]; then
    echo "Timed out waiting for ingestion lag to drop to zero"
    exit 1
fi

echo "Ingestion lag dropped to zero after $SECONDS seconds"

# Kill the plugin server process and poll for up to 30 seconds for it to exit.
kill $(jobs -p)

SECONDS=0

while [[ $SECONDS -lt 30 ]]; do
    if ! pgrep -f "pnpm start:dev" > /dev/null; then
        break
    fi
    sleep 1
done

# Print the plugin server logs.
echo "::group::Plugin server logs"
cat /tmp/plugin-server.log
echo "::endgroup::"
