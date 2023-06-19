CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TABLE destinations (
    primary_key integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    -- A unique identifier for this destination that does not expose
    -- cardinality.
    id uuid NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
    -- NOTE: we use team_id here to be consistent with the rest of the app,
    -- but this is the id of a project.
    team_id bigint NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    -- The type of destination. This is used to determine which
    -- destination-specific configuration to use.
    type text NOT NULL,
    -- The destination-specific configuration. This is a JSON object
    -- that is specific to the destination type.
    config jsonb NOT NULL,
    -- Metadata about the destination.
    created_at timestamp NOT NULL DEFAULT now(),
    created_by_id bigint NOT NULL,
    updated_at timestamp NOT NULL DEFAULT now(),
    is_deleted boolean NOT NULL DEFAULT false
);
