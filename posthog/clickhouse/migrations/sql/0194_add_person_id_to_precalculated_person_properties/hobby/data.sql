DROP TABLE IF EXISTS precalculated_person_properties

ALTER TABLE sharded_precalculated_person_properties
    ADD COLUMN IF NOT EXISTS person_id UUID AFTER distinct_id

CREATE TABLE IF NOT EXISTS precalculated_person_properties
(
    team_id Int64,
    distinct_id String,
    person_id UUID,
    condition String,
    matches Bool,
    source String,
    _timestamp DateTime64(6),
    _offset UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_precalculated_person_properties', sipHash64(distinct_id))
