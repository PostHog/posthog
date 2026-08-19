# Shared dev-environment plumbing for bin/start and bin/worktree-stack.
# Sourced by both so the env-file parsing rules and the computed connection
# URLs cannot drift between the main stack and worktree stacks.

# Source env files respecting precedence:
#   shell env > .env.local > .env.development > .env.services
# Only set vars that aren't already in the environment.
# op:// refs are always skipped here — they only get resolved by `op run` in
# bin/start's re-exec block. Sourcing them as literals would set env vars to
# garbage strings that break downstream services with cryptic errors.
source_env_defaults() {
    if [[ ! -f "$1" ]]; then
        echo "⚠️  Expected env file missing: $1 — skipping. Did your checkout get truncated?" >&2
        return 0
    fi
    # Use explicit if/fi (not `[[ ... ]] && cmd`) so the loop body always
    # returns 0. With `&&`, the last iteration's `[[ -z … ]]` returning false
    # (variable already set) makes the function return non-zero, and `set -e`
    # silently kills the entire script — no error, no output, just exit. This
    # was the root cause of "hogli start" failing in Cursor and other terminals
    # where some of the trailing env vars happened to already be in the shell.
    while IFS='=' read -r name value; do
        [[ -z "$name" || "$name" == \#* ]] && continue
        # Substring match so quoted ("op://...") and space-padded values are
        # also caught — mirrors what op run itself accepts.
        [[ "$value" == *op://* ]] && continue
        if [[ -z "${!name:-}" ]]; then
            export "$name=$value"
        fi
    done < "$1"
    return 0
}

# Connection URLs whose defaults need bash variable expansion (${PGHOST:-db},
# $PERSONS_DATABASE_URL, etc.) — they can't live in .env.development because
# the loader above doesn't re-expand $-refs.
export_computed_connection_urls() {
    # Persons DB — Node.js and Rust use different env var names for the same connection
    export PERSONS_DATABASE_URL=${PERSONS_DATABASE_URL:-postgres://posthog:posthog@${PGHOST:-db}:${PGPORT:-5432}/posthog_persons}
    export PERSONS_READONLY_DATABASE_URL=${PERSONS_READONLY_DATABASE_URL:-postgres://posthog:posthog@${PGHOST:-db}:${PGPORT:-5432}/posthog_persons}
    # nosemgrep: env-default-belongs-in-env-development -- bash variable ref in default
    export PERSONS_WRITE_DATABASE_URL=${PERSONS_WRITE_DATABASE_URL:-$PERSONS_DATABASE_URL}
    # nosemgrep: env-default-belongs-in-env-development -- bash variable ref in default
    export PERSONS_READ_DATABASE_URL=${PERSONS_READ_DATABASE_URL:-$PERSONS_READONLY_DATABASE_URL}
    # nosemgrep: env-default-belongs-in-env-development -- bash variable ref in default
    export PERSONS_DB_WRITER_URL=${PERSONS_DB_WRITER_URL:-$PERSONS_DATABASE_URL}
    # nosemgrep: env-default-belongs-in-env-development -- bash variable ref in default
    export PERSONS_DB_READER_URL=${PERSONS_DB_READER_URL:-$PERSONS_READONLY_DATABASE_URL}
    export BEHAVIORAL_COHORTS_DATABASE_URL=${BEHAVIORAL_COHORTS_DATABASE_URL:-postgres://posthog:posthog@${PGHOST:-db}:${PGPORT:-5432}/behavioral_cohorts}
    export FLAGS_READ_STORE_DATABASE_URL=${FLAGS_READ_STORE_DATABASE_URL:-postgres://posthog:posthog@${PGHOST:-db}:${PGPORT:-5432}/flags_read_store}
    export CYCLOTRON_DATABASE_URL=${CYCLOTRON_DATABASE_URL:-postgres://posthog:posthog@${PGHOST:-db}:${PGPORT:-5432}/cyclotron}
    export CYCLOTRON_NODE_DATABASE_URL=${CYCLOTRON_NODE_DATABASE_URL:-postgres://posthog:posthog@${PGHOST:-db}:${PGPORT:-5432}/cyclotron_node}
}
