-- Persons DB schema for test harness with secondary DB (secondary DB used by dual-write)
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
    distinct_id VARCHAR(400) NOT NULL,
    person_id BIGINT NOT NULL,
    team_id INTEGER NOT NULL,
    version BIGINT NULL
);

-- Add both foreign key constraints to match production schema
-- The deferred constraint needs CASCADE for delete operations to work
-- Drop constraints if they exist first to ensure clean state
DO $$ 
BEGIN
    ALTER TABLE posthog_persondistinctid 
        DROP CONSTRAINT IF EXISTS posthog_persondistin_person_id_5d655bba_fk_posthog_p;
    ALTER TABLE posthog_persondistinctid 
        DROP CONSTRAINT IF EXISTS posthog_persondistinctid_person_id_5d655bba_fk;
    
    ALTER TABLE posthog_persondistinctid 
        ADD CONSTRAINT posthog_persondistin_person_id_5d655bba_fk_posthog_p 
        FOREIGN KEY (person_id) 
        REFERENCES posthog_person(id) 
        ON DELETE CASCADE
        DEFERRABLE INITIALLY DEFERRED;

    ALTER TABLE posthog_persondistinctid 
        ADD CONSTRAINT posthog_persondistinctid_person_id_5d655bba_fk 
        FOREIGN KEY (person_id) 
        REFERENCES posthog_person(id)
        ON DELETE CASCADE;
END $$;

-- Create the unique constraint (not just index) to match production
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'unique distinct_id for team' 
        AND conrelid = 'posthog_persondistinctid'::regclass
    ) THEN
        ALTER TABLE posthog_persondistinctid
            ADD CONSTRAINT "unique distinct_id for team"
            UNIQUE (team_id, distinct_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS posthog_persondistinctid_person_id_5d655bba
    ON posthog_persondistinctid (person_id);

-- Personless distinct IDs (merge queue helpers)
CREATE TABLE IF NOT EXISTS posthog_personlessdistinctid (
    team_id INTEGER NOT NULL,
    distinct_id TEXT NOT NULL,
    is_merged BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, distinct_id)
);

-- Cohort membership by person (only person_id is touched by repo)
CREATE TABLE IF NOT EXISTS posthog_cohortpeople (
    id BIGSERIAL PRIMARY KEY,
    cohort_id INTEGER NOT NULL,
    person_id BIGINT NOT NULL,
    version INTEGER NULL
);

-- Add both foreign key constraints to match production schema
ALTER TABLE posthog_cohortpeople
    ADD CONSTRAINT posthog_cohortpeople_person_id_33da7d3f_fk_posthog_person_id
    FOREIGN KEY (person_id)
    REFERENCES posthog_person(id)
    ON DELETE CASCADE
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE posthog_cohortpeople
    ADD CONSTRAINT posthog_cohortpeople_person_id_33da7d3f_fk
    FOREIGN KEY (person_id)
    REFERENCES posthog_person(id)
    ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS posthog_cohortpeople_person_id_33da7d3f
    ON posthog_cohortpeople (person_id);

-- Index from Django model Meta class
CREATE INDEX IF NOT EXISTS posthog_cohortpeople_cohort_person_idx
    ON posthog_cohortpeople (cohort_id, person_id);

-- Feature flag hash key overrides (referenced during person merges)
CREATE TABLE IF NOT EXISTS posthog_featureflaghashkeyoverride (
    id BIGSERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL,
    person_id BIGINT NOT NULL,
    feature_flag_key TEXT NOT NULL,
    hash_key TEXT NOT NULL
);

-- Add both foreign key constraints to match production schema
ALTER TABLE posthog_featureflaghashkeyoverride
    ADD CONSTRAINT posthog_featureflagh_person_id_7e517f7c_fk_posthog_p
    FOREIGN KEY (person_id)
    REFERENCES posthog_person(id)
    ON DELETE CASCADE
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE posthog_featureflaghashkeyoverride
    ADD CONSTRAINT posthog_featureflaghashkeyoverride_person_id_7e517f7c_fk
    FOREIGN KEY (person_id)
    REFERENCES posthog_person(id)
    ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS posthog_featureflaghashkeyoverride_person_id_7e517f7c
    ON posthog_featureflaghashkeyoverride (person_id);