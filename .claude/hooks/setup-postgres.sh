#!/bin/bash
# Bring up a local PostgreSQL and create the posthog role/database used by the Rust
# integration tests (e.g. property-defs-rs uses #[sqlx::test], which needs a live
# DATABASE_URL). Docker isn't available in the web container, so we drive the natively
# installed cluster directly. Best-effort and idempotent: it must never fail the session.

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

command -v pg_ctlcluster >/dev/null 2>&1 || exit 0

# Newest installed major version (e.g. "16"); reliable even if pg_lsclusters is unavailable.
PG_VER=$(ls /usr/lib/postgresql/ 2>/dev/null | sort -n | tail -1)
[ -n "$PG_VER" ] || exit 0

# Start the cluster if it isn't already accepting connections.
if ! pg_isready -h localhost >/dev/null 2>&1; then
    pg_ctlcluster "$PG_VER" main start >/dev/null 2>&1 || true
    for _ in $(seq 1 10); do
        pg_isready -h localhost >/dev/null 2>&1 && break
        sleep 1
    done
fi

# Create the posthog superuser role + database the tests expect (idempotent).
if pg_isready -h localhost >/dev/null 2>&1; then
    if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='posthog'" 2>/dev/null | grep -q 1; then
        runuser -u postgres -- psql -c "CREATE ROLE posthog WITH LOGIN PASSWORD 'posthog' SUPERUSER CREATEDB" >/dev/null 2>&1 || true
    fi
    if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='posthog'" 2>/dev/null | grep -q 1; then
        runuser -u postgres -- createdb -O posthog posthog >/dev/null 2>&1 || true
    fi
fi

# Expose connection settings for the session. The Rust crates compile against the committed
# .sqlx cache (SQLX_OFFLINE=true); a live DATABASE_URL is only needed at test runtime, where
# #[sqlx::test] creates and drops its own ephemeral databases.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo 'export DATABASE_URL="postgres://posthog:posthog@localhost:5432/posthog"' >> "$CLAUDE_ENV_FILE"
    echo 'export SQLX_OFFLINE=true' >> "$CLAUDE_ENV_FILE"
fi

exit 0
