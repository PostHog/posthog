#!/bin/bash
set -e

# I set all possible env vars here, tune them as you like
export RUST_LOG="INFO"
export HOST="::"
export PORT="3302"
export DATABASE_URL="postgres://posthog:posthog@localhost:5432/cyclotron"
export CLEANUP_INTERVAL_SECONDS="10"
export PG_MAX_CONNECTIONS="10"
export PG_MIN_CONNECTIONS="1"
export PG_ACQUIRE_TIMEOUT_SECONDS="5"
export PG_MAX_LIFETIME_SECONDS="300"
export PG_IDLE_TIMEOUT_SECONDS="60"
export JANITOR_ID="test-janitor"
export JANITOR_MAX_TOUCHES="2"
export JANITOR_STALL_TIMEOUT_SECONDS="30"

# Uncomment this to have the database be reset every time you start the janitor
sqlx database reset -y --source ../cyclotron-core/migrations
sqlx migrate run --source ../cyclotron-core/migrations

cargo run --release