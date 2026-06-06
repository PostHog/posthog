# This migration originally created test tables for validating the error tracking
# Node ingestion pipeline. Those tables have been dropped in migration 0224 now
# that the pipeline is in production. This migration is intentionally left as a
# no-op so new environments don't create tables that will immediately be dropped.

operations: list = []
