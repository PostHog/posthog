#!/usr/bin/env bash

# Script for running the functional tests in CI, outputting an Istambul coverage
# report. When running the intetgration tests locally, it's probably better to
# simply run `yarn functional_tests` directly which will allow e.g. to watch for
# changes. This script is intended to handle the complexities of spinning up the
# plugin server with the appropriate environment vars setup, and ensuring we
# bring down the server such that c8 produces the coverage report.
# Context is this was originally written in the GitHub Actions workflow file,
# but it's easier to debug in a script.

set -ex -o pipefail

export WORKER_CONCURRENCY=1
export CONVERSION_BUFFER_ENABLED=true
export BUFFER_CONVERSION_SECONDS=2 # Make sure we don't have to wait for the default 60 seconds
export KAFKA_MAX_MESSAGE_BATCH_SIZE=0
export APP_METRICS_GATHERED_FOR_ALL=true

LOG_FILE=$(mktemp)

echo '::group::Starting plugin server'

./node_modules/.bin/c8 --reporter html node dist/index.js > $LOG_FILE 2>&1 &
SERVER_PID=$!

until curl http://localhost:6738/_ready; do
    echo 'Waiting for plugin-server to be ready...'
    echo ''
    sleep 1
done

echo '::endgroup::'

set +e
yarn functional_tests --maxConcurrency=10 --verbose
exit_code=$?
set -e

kill $SERVER_PID
wait $SERVER_PID

if [ $exit_code -ne 0 ]; then
    echo '::group::Plugin Server logs'
    cat $LOG_FILE
    echo '::endgroup::'
fi

exit $exit_code
