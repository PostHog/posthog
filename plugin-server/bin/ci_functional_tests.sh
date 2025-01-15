#!/usr/bin/env bash

# Script for running the functional tests in CI, outputting an Istambul coverage
# report. When running the intetgration tests locally, it's probably better to
# simply run `pnpm functional_tests` directly which will allow e.g. to watch for
# changes. This script is intended to handle the complexities of spinning up the
# plugin server with the appropriate environment vars setup, and ensuring we
# bring down the server such that c8 produces the coverage report.
# Context is this was originally written in the GitHub Actions workflow file,
# but it's easier to debug in a script.

set -e -o pipefail

export WORKER_CONCURRENCY=1
export KAFKA_MAX_MESSAGE_BATCH_SIZE=0
export APP_METRICS_FLUSH_FREQUENCY_MS=0 # Reduce the potential for spurious errors in tests that wait for metrics
export APP_METRICS_GATHERED_FOR_ALL=true
export PLUGINS_DEFAULT_LOG_LEVEL=0 # All logs, as debug logs are used in synchronization barriers
export NODE_ENV=production-functional-tests
export PLUGIN_SERVER_MODE=functional-tests # running all capabilities is too slow

# Not important at all, but I like to see nice red/green for tests
export FORCE_COLOR=true

LOG_FILE=$(mktemp)

echo '::group::Starting plugin server'

NODE_OPTIONS='--max_old_space_size=4096' ./node_modules/.bin/c8 --reporter html node dist/index.js >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
SECONDS=0

until curl http://localhost:6738/_ready; do
    if ((SECONDS > 60)); then
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

echo '::endgroup::'

set +e
pnpm functional_tests --maxConcurrency=10 --verbose
exit_code=$?
set -e

kill $SERVER_PID
SECONDS=0

while kill -0 $SERVER_PID; do
    if ((SECONDS > 60)); then
        echo 'Timed out waiting for plugin-server to exit'
        break
    fi

    echo "Waiting for plugin-server to exit, pid $SERVER_PID..."
    sleep 1
done

echo '::group::Plugin Server logs'
cat "$LOG_FILE"
echo '::endgroup::'

exit $exit_code
