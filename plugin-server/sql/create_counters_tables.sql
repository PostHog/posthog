-- Create the counters database tables
-- This file is used to set up the counters database structure
-- Database creation is handled by the setup script

-- Table for person performed events
CREATE TABLE IF NOT EXISTS person_performed_events (
    team_id INTEGER NOT NULL,
    person_id UUID NOT NULL,
    event_name TEXT NOT NULL,
    PRIMARY KEY (team_id, person_id, event_name)
);

-- Index for efficient lookups by team_id and person_id
CREATE INDEX IF NOT EXISTS idx_person_performed_events_team_person 
ON person_performed_events (team_id, person_id);

-- Table for behavioural filter matched events
CREATE TABLE IF NOT EXISTS behavioural_filter_matched_events (
    team_id INTEGER NOT NULL,
    person_id UUID NOT NULL,
    filter_hash TEXT NOT NULL,
    date DATE NOT NULL,
    counter INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (team_id, person_id, filter_hash, date)
);

-- Index for queries by just team_id and person_id
CREATE INDEX IF NOT EXISTS idx_behavioural_filter_team_person 
ON behavioural_filter_matched_events (team_id, person_id);

-- Grant permissions if needed (adjust user as necessary)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO posthog;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO posthog;