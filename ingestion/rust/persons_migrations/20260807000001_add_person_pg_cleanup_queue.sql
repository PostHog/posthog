-- Handoff queue from the ClickHouse cleanup sweep to the Postgres one.
--
-- The ClickHouse sweep hard-deletes a deleted person's rows, and once it does,
-- the tombstones it derived that set from are gone. So it records each person
-- here first, and a later job drains this queue to clear posthog_person and
-- posthog_persondistinctid.
--
-- team_id is carried because posthog_person is 64-way HASH (team_id): the
-- drain resolves uuid -> id through the unique (team_id, uuid) index, which
-- prunes to one partition. Without team_id it fans out across all 64.
--
-- Only the person UUID is stored. ClickHouse has no integer person id, so the
-- BIGINT posthog_person.id is resolved by the drain rather than carried here.
--
-- SAFE: creates a new empty table and index only; takes no locks on existing
-- tables. Idempotent and safe to re-run.

CREATE TABLE IF NOT EXISTS person_pg_cleanup_queue (
    team_id     INTEGER NOT NULL,
    person_uuid UUID NOT NULL,
    deleted_at  TIMESTAMP WITH TIME ZONE NOT NULL,  -- when the ClickHouse sweep finished
    cleaned_at  TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (team_id, person_uuid)              -- lets the sweep re-run without duplicating rows
);

-- Drain scan: least-recently-queued rows still awaiting Postgres cleanup.
CREATE INDEX IF NOT EXISTS person_pg_cleanup_queue_drain
    ON person_pg_cleanup_queue (deleted_at)
    WHERE cleaned_at IS NULL;
