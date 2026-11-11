-- Lifecycle-manager saga state tables.
--
-- Every person-destroying operation (merge, delete) runs as a durable saga:
-- one lifecycle_op row per operation (current step, lease, frozen request,
-- recorded outcome) and one lifecycle_op_person row per person the operation
-- touches (the claim, plus everything captured about the person before it is
-- destroyed). Living on the same primary as the person rows lets each PG step
-- commit its work and its step advance in one transaction.
--
-- SAFE: creates new empty tables and indexes only; takes no locks on
-- existing tables. This migration is idempotent and safe to re-run.

CREATE TABLE IF NOT EXISTS lifecycle_op (
    op_id            UUID PRIMARY KEY,   -- caller-supplied (event uuid / GDPR job id)
    op_type          TEXT NOT NULL CHECK (op_type IN ('merge', 'delete')),
    team_id          INTEGER NOT NULL,
    step             TEXT NOT NULL,
    attempt          INTEGER NOT NULL DEFAULT 0,  -- sweeper takeovers; alert above a threshold
    lease_expires_at TIMESTAMP WITH TIME ZONE,    -- the expiry is the lock; owner identity goes to logs
    request          JSONB NOT NULL,     -- frozen caller request
    outcome          JSONB,              -- per-person outcomes; the recorded answer for op_id retries
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    completed_at     TIMESTAMP WITH TIME ZONE
);

-- Sweeper scan: incomplete ops whose lease has expired.
CREATE INDEX IF NOT EXISTS lifecycle_op_sweep ON lifecycle_op (lease_expires_at)
    WHERE completed_at IS NULL;

-- Garbage collection: completed ops past retention.
CREATE INDEX IF NOT EXISTS lifecycle_op_gc ON lifecycle_op (completed_at)
    WHERE completed_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS lifecycle_op_person (
    op_id       UUID NOT NULL REFERENCES lifecycle_op (op_id) ON DELETE CASCADE,
    team_id     INTEGER NOT NULL,
    person_id   BIGINT NOT NULL,
    person_uuid UUID NOT NULL,
    role        TEXT NOT NULL,           -- target | source (merge) | victim (delete)
    ordinal     INTEGER,                 -- pair order: property precedence (merge sources only)
    status      TEXT NOT NULL,           -- marked | sealed | deleted | cleared (target)
                                         -- | skipped_conflict | skipped_identified
                                         -- | skipped_move_limit
    sealed      JSONB,                   -- frozen at the fence: version, created_at,
                                         -- is_identified, properties (merge only)
    moved       JSONB,                   -- written by the flip/tombstone TX, in the same
                                         -- commit that repoints or tombstones the rows:
                                         -- [(distinct_id, new_version), ...]
    PRIMARY KEY (op_id, person_id)
);

-- The mark: at most one live op may claim a person.
-- Inserting a row is marking; a unique violation IS the conflict.
CREATE UNIQUE INDEX IF NOT EXISTS lifecycle_op_person_mark
    ON lifecycle_op_person (team_id, person_id)
    WHERE status IN ('marked', 'sealed');
