# This migration originally dropped test tables for the error tracking Node
# ingestion pipeline. The tables have been dropped in production and the
# underlying SQL definitions removed. This migration is intentionally left as
# a no-op so it remains in the migration history without referencing deleted code.

operations: list = []
