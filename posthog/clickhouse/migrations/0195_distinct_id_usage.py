# Migration 0195 originally created distinct_id_usage tables, but these were
# dropped in migration 0202 and recreated with a different architecture in 0203.
# This migration is now a no-op to avoid issues with the SQL functions changing.

operations: list = []
