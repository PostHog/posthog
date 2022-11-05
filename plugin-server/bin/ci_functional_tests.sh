#!/usr/bin/env bash

# Script for running the functional tests in CI, outputting an Istambul coverage
# report. When running the intetgration tests locally, it's probably better to
# simply run `pnpm functional_tests` directly which will allow e.g. to watch for
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

./node_modules/.bin/c8 --reporter html node dist/index.js &
SERVER_PID=$!

until curl http://localhost:6738/_ready; do
    echo ''
    echo 'Waiting for plugin-server to be ready...'
    sleep 1
done

set +e
pnpm functional_tests --maxConcurrency=10
exit_code=$?
set -e

kill $SERVER_PID
wait $SERVER_PID

exit $exit_code
