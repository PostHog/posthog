-- Migration: Create behavioral event counters table
-- Created: 2025-07-23
-- Description: Table to store real-time behavioral event match counters
-- Supports the RFC for real-time behavioral filtering (cohorts)

-- Create the behavioral event counters table
-- This table stores counters for action filter matches with the pattern:
-- team_id:filter_hash:person_id:date
CREATE TABLE IF NOT EXISTS behavioral_event_counters (
    team_id INT,
    filter_hash TEXT,
    person_id UUID,
    date DATE,
    count COUNTER,
    PRIMARY KEY (team_id, filter_hash, person_id, date)
) WITH CLUSTERING ORDER BY (filter_hash ASC, person_id ASC, date DESC);

-- Note: Cannot create secondary index on counter table
-- Time-range queries should use the primary key (team_id, filter_hash, person_id, date)