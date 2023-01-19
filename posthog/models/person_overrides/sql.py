# Within PostHog, it is possible that two Persons are merged together. The
# impact of this is that all events that were associated with the Persons should
# now appear to be associated with a single Person.
#
# In the ClickHouse `sharded_events` tabke we gave a `person_id` column that
# contains the UUID of the Person that the event is associated with. When a
# merge happens, we do not immediately update the `person_id` column in the
# `sharded_events` table. Instead, we create a new row in the `person_overrides`
# table that contains the mapping from the `old_person_id` to the
# `override_person_id`. This allows us to OUTER JOIN the `person_overrides`
# table to the `sharded_events` table to find all events that were associated
# and therefore reconcile the events to be associated with the same Person.

PERSON_OVERRIDES_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS person_overrides (
        team_id INT NOT NULL,

        -- When we merge two people `old_person_id` and `override_person_id`, we
        -- want to keep track of a mapping from the `old_person_id` to the
        -- `override_person_id`. This allows us to join with the
        -- `sharded_events` table to find all events that were associated with
        -- the `old_person_id` and update them to be associated with the
        -- `override_person_id`.
        old_person_id UUID NOT NULL,
        override_person_id UUID NOT NULL,

        -- The timestamp rows are created.
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        -- The timestamp the merge of the two people was completed.
        merged_at TIMESTAMP WITH TIME ZONE NOT NULL

        -- the specific version of the `old_person_id` mapping. This is used to
        -- allow us to discard old mappings as new ones are added.
        version INT NOT NULL,
    )
    -- By specifying Replacing merge tree on version, we allow ClickHouse to
    -- discard old versions of a `old_person_id` mapping. This should help keep
    -- performance in check as new versions are added.
    --
    -- We also need to ensure that the data is replicated to all replicas in the
    -- cluster, as we do not have any constraints on person_id and which shard
    -- associated events are on.
    ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_overrides', '{replica}-{shard}', version)

    -- We want to collapse down on the `old_person_id` such that we end up with
    -- the newest known mapping for it in the table. Query side we will need to
    -- ensure that we are always querying the latest version of the mapping.
    ORDER BY (team_id, old_person_id)
"""

# TODO: add KafkaTables
