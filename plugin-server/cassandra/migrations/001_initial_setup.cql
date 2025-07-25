-- Initial setup migration for PostHog Cassandra keyspace
-- This migration creates the keyspace (handled automatically by the runner)
-- and serves as a marker for the first migration

-- Create a simple test table to verify the migration system works
CREATE TABLE IF NOT EXISTS migration_test (
    id UUID PRIMARY KEY,
    created_at TIMESTAMP,
    message TEXT
);