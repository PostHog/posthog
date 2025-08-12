-- Persons DB schema fro tests (secondary DB used by dual-write)
-- Minimal compatible DDL for PostgresPersonRepository operations for testing

CREATE TABLE IF NOT EXISTS posthog_person (
    id BIGSERIAL PRIMARY KEY,
    uuid UUID NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    team_id INTEGER NOT NULL,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    properties_last_updated_at JSONB NOT NULL DEFAULT '{}'::jsonb,
    properties_last_operation JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_user_id INTEGER NULL,
    is_identified BOOLEAN NOT NULL DEFAULT false,
    version BIGINT NULL
);

-- Helpful index for updatePersonAssertVersion
CREATE INDEX IF NOT EXISTS posthog_person_team_uuid_idx
    ON posthog_person (team_id, uuid);

-- Distinct IDs
CREATE TABLE IF NOT EXISTS posthog_persondistinctid (
    id BIGSERIAL PRIMARY KEY,
    distinct_id TEXT NOT NULL,
    person_id BIGINT NOT NULL REFERENCES posthog_person(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL,
    version BIGINT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS posthog_persondistinctid_team_distinct_idx
    ON posthog_persondistinctid (team_id, distinct_id);

CREATE INDEX IF NOT EXISTS posthog_persondistinctid_person_idx
    ON posthog_persondistinctid (person_id);

-- Personless distinct IDs (merge queue helpers)
CREATE TABLE IF NOT EXISTS posthog_personlessdistinctid (
    team_id INTEGER NOT NULL,
    distinct_id TEXT NOT NULL,
    is_merged BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, distinct_id)
);

-- NICKS TODO: remove a bunch of these to find out what is actually needed in this file
-- Cohort membership by person (only person_id is touched by repo)
CREATE TABLE IF NOT EXISTS posthog_cohortpeople (
    id BIGSERIAL PRIMARY KEY,
    cohort_id INTEGER NOT NULL,
    person_id BIGINT NOT NULL,
    team_id INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS posthog_cohortpeople_person_idx
    ON posthog_cohortpeople (person_id);

-- Feature flag hash key overrides (referenced during person merges)
CREATE TABLE IF NOT EXISTS posthog_featureflaghashkeyoverride (
    id BIGSERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL,
    person_id BIGINT NOT NULL,
    feature_flag_key TEXT NOT NULL,
    hash_key TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS posthog_featureflaghashkeyoverride_person_idx
    ON posthog_featureflaghashkeyoverride (person_id);