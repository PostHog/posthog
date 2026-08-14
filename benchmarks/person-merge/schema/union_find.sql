-- Union-find extension over the current schema: a merged person stays in
-- place and points at its survivor instead of having its mappings moved.
ALTER TABLE posthog_person ADD COLUMN merged_into_id BIGINT;

-- Child lookup for collecting a union's members (compat emissions, compaction).
CREATE INDEX posthog_person_merged_into_idx
    ON posthog_person (merged_into_id)
    WHERE merged_into_id IS NOT NULL;
