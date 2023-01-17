PERSON_MERGES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS posthog_personmerges (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    team_id INT NOT NULL,

    merged_from_person_id UUID NOT NULL,
    merged_into_person_id UUID NOT NULL,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    merged_at TIMESTAMP WITH TIME ZONE NOT NULL
) ENGINE = MergeTree()
"""

# TODO: add sort key
# TODO: add appropriate merge strategy for allowing cycling out person_ids that
# are no longer required.
# TODO: add replication or distributed table for writes
# TODO: add KafkaTables
