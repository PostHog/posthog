-- Add indexes and foreign key constraints for partitioned person table
-- This creates indexes on partition id columns and re-establishes foreign keys

-- Create index on id column for each partition to optimize lookups
DO $$
DECLARE
    num_partitions INTEGER := 64;
    i INTEGER;
BEGIN
    FOR i IN 0..(num_partitions - 1) LOOP
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS posthog_person_p%s_id_idx ON public.posthog_person_p%s USING btree (id)',
            i, i
        );
    END LOOP;
END $$;

-- Re-add foreign key constraint pointing to the new partitioned table
-- Using NOT VALID to avoid scanning existing data during migration
-- The constraint will be validated in a later migration after data is migrated

-- FK from posthog_persondistinctid to posthog_person_new
ALTER TABLE posthog_persondistinctid
    ADD CONSTRAINT posthog_persondistinctid_person_id_fkey
    FOREIGN KEY (team_id, person_id) REFERENCES posthog_person_new(team_id, id) NOT VALID;
