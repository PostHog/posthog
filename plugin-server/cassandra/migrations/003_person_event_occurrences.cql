-- Migration: Create person event occurrences table
-- Created: 2025-07-25
-- Description: Table to track whether a person has performed a specific event
-- Optimized for occurrence tracking (set semantics) with efficient queries by person_id and event_name

-- Create the person event occurrences table
-- This table stores occurrences with the pattern:
-- team_id:person_id:event_name
-- If a record exists, the event occurred
CREATE TABLE IF NOT EXISTS person_event_occurrences (
    team_id INT,
    person_id UUID,  
    event_name TEXT,
    PRIMARY KEY (team_id, person_id, event_name)
) WITH CLUSTERING ORDER BY (person_id ASC, event_name ASC)
  AND compaction = {
    'class': 'LeveledCompactionStrategy',
    'sstable_size_in_mb': 1024
  };

-- Note: Using LeveledCompactionStrategy for read-heavy workloads with frequent updates
-- The table is optimized for queries by team_id + person_id + event_name
-- Using default gc_grace_seconds (10 days) initially - can be tuned based on actual usage patterns