-- personhog-identity can be pointed at this table via PERSON_TABLE; its read
-- paths select is_user_id, which the original mirror omitted. Nullable and
-- never written by personhog, so it stays NULL — present only so the mirror
-- serves the same column set as posthog_person.
ALTER TABLE personhog_person_tmp ADD COLUMN IF NOT EXISTS is_user_id INTEGER;
