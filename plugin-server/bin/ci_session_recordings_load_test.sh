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

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"

# The number of sessions to generate and ingest, defaulting to 10 if not already
# set.
SESSIONS_COUNT=${SESSIONS_COUNT:-10}
TOKEN=e2e_token_1239 # Created by the setup_dev management command.

LOG_FILE=$(mktemp)

# If GITHUB_STEP_SUMMARY isn't already set, set it to a temporary file. This is
# used to store the Workflow step summary, but when run locally we do not have
# this set.
if [[ -z "${GITHUB_STEP_SUMMARY:-}" ]]; then
    GITHUB_STEP_SUMMARY=$(mktemp)
fi

SESSION_RECORDING_EVENTS_TOPIC=session_recording_events
SESSION_RECORDING_INGESTION_CONSUMER_GROUP=session-recordings

export KAFKAJS_NO_PARTITIONER_WARNING=1

# Wait for Kafka to be ready, give it 30 seconds
SECONDS=0

until docker compose \
    -f "$DIR"/../../docker-compose.dev.yml exec \
    -T kafka kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --list \
    >/dev/null; do
    if ((SECONDS > 30)); then
        echo 'Timed out waiting for Kafka to be ready'
        exit 1
    fi

    echo ''
    echo 'Waiting for Kafka to be ready...'
    sleep 1
done

# Make sure the topic exists, and if not, create it.
echo "Creating topic $SESSION_RECORDING_EVENTS_TOPIC"
docker compose \
    -f "$DIR"/../../docker-compose.dev.yml exec \
    -T kafka kafka-topics.sh \
    --bootstrap-server localhost:9092 \
    --create \
    --topic $SESSION_RECORDING_EVENTS_TOPIC \
    --partitions 1 \
    --replication-factor 1 >/dev/null 2>&1 ||
    echo 'Topic already exists'

# Before we do anything, reset the consumer group offsets to the latest offsets.
# This is to ensure that we are only testing the ingestion of new messages, and
# not the replay of old messages. We don't fail if the topic does not exist.
# Note that we need to use the `--execute` flag to actually reset the offsets.
echo "Resetting consumer group offsets to latest"
docker compose \
    -f "$DIR"/../../docker-compose.dev.yml exec \
    -T kafka kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 \
    --reset-offsets \
    --to-latest \
    --execute \
    --group $SESSION_RECORDING_INGESTION_CONSUMER_GROUP \
    --topic $SESSION_RECORDING_EVENTS_TOPIC >/dev/null 2>&1

# Generate the session recording events and send them to Kafka.
echo "Generating $SESSIONS_COUNT session recording events"
"$DIR"/generate_session_recordings_messages.py \
    --count "$SESSIONS_COUNT" \
    --token $TOKEN |
    docker compose \
        -f "$DIR"/../../docker-compose.dev.yml exec \
        -T kafka kafka-console-producer.sh \
        --topic $SESSION_RECORDING_EVENTS_TOPIC \
        --broker-list localhost:9092

# Start the plugin server with only the session recordings consumer running. We
# need to make sure that we terminate the backgrounded process on exit, so we
# use the `trap` command to kill all backgrounded processes when the last one
# terminates.
# NOTE: we start te plugin-server after we have published to Kafka, as we want
# to remove any of the time it takes to publish the messages to Kafka. There
# will be some time between the plugin server starting and the consumer group
# being ready to consume messages, so we want to add a sufficient number of
# messages if we want to make this time insignificant.
echo "Starting plugin-server, logging to $LOG_FILE"
PLUGIN_SERVER_MODE=recordings-ingestion "$DIR"/../node_modules/.bin/0x --output-dir=./profile/ dist/index.js >"$LOG_FILE" 2>&1 &
SERVER_PID=$!

# On exit, see if the process is still running, and if so, kill it. We also
# print the plugin server logs in this case as we assume that we are in a
# situation where we didn't make it to the end.
trap 'if kill -0 $SERVER_PID; then echo "Killing plugin server"; kill %; echo "::group::Plugin Server logs"; cat "$LOG_FILE"; echo "::endgroup::"; fi' EXIT

# Wait for the plugin server health check to be ready, and timeout after 10
# seconds with exit code 1.
SECONDS=0

until curl http://localhost:6738/_health; do

    if ((SECONDS > 20)); then
        echo 'Timed out waiting for plugin-server to be ready'
        echo '::endgroup::'
        echo '::group::Plugin Server logs'
        cat "$LOG_FILE"
        echo '::endgroup::'
        exit 1
    fi

    echo ''
    echo 'Waiting for plugin-server to be ready...'
    sleep 1
done

echo ''
echo 'Plugin server is ready'

# Wait for the ingestion lag for the session recordings consumer group for the
# session recording events topic to drop to zero, timing out after 120 seconds
# with exit code 1. We also print progress of the lag every second.
SECONDS=0

while [[ $SECONDS -lt 120 ]]; do
    OUTPUT=$(docker compose \
        -f "$DIR"/../../docker-compose.dev.yml exec \
        -T kafka kafka-consumer-groups.sh \
        --bootstrap-server localhost:9092 \
        --describe \
        --group $SESSION_RECORDING_INGESTION_CONSUMER_GROUP | grep $SESSION_RECORDING_EVENTS_TOPIC)

    LAG=$(echo "$OUTPUT" | awk '{print $6}')

    echo "Group info: $OUTPUT"

    echo "Ingestion lag: $LAG"

    # Check if the LAG string is "0"
    if [[ $LAG == "0" ]]; then
        break
    fi

    sleep 1
done

if [[ $SECONDS -ge 120 ]]; then
    echo "Timed out waiting for ingestion lag to drop to zero"
    cat /tmp/plugin-server.log
    exit 1
fi

# Print the time it took for the ingestion lag to drop to zero, and sessions per
# second that were ingested.
echo "Ingestion lag dropped to zero after $SECONDS seconds"

SESSIONS_PER_SECOND=$(echo "$SESSIONS_COUNT $SECONDS" | awk '{printf "%.2f", $1 / $2}')
echo "Sessions per second: $SESSIONS_PER_SECOND" | tee -a "$GITHUB_STEP_SUMMARY"

# Kill the plugin server process and poll for up to 60 seconds for it to exit.
kill %
SECONDS=0

while kill -0 $SERVER_PID; do
    if ((SECONDS > 60)); then
        echo 'Timed out waiting for plugin-server to exit'
        break
    fi

    echo "Waiting for plugin-server to exit, pid $SERVER_PID..."
    sleep 1
done

# Print the plugin server logs.
echo "::group::Plugin server logs"
cat "$LOG_FILE"
echo "::endgroup::"
