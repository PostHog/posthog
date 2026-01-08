# Pre-migrated Database Dumps

This directory contains a pre-migrated PostgreSQL database dump that provides a fast starting point for database setup.

## Usage

The dump is automatically used when:

- Running tests (pytest)
- Running E2E tests (bin/e2e-test-runner)
- Setting up fresh databases in CI

The dump is restored to provide a fast starting point, then **migrations are always run** to apply any new migrations that were added since the dump was created. This gives you the speed benefit of the dump (skipping historical migrations) while ensuring all migrations are applied.

## Generating a Dump

To generate or update the dump:

1. Clean your local databases:

   ```bash
   dropdb posthog posthog_persons behavioral_cohorts cyclotron
   ```

2. Generate the dump:

   ```bash
   bin/generate-pre-migrated-dump
   ```

   Or using hogli:

   ```bash
   hogli db:generate-dump
   ```

3. Commit the updated dump:

   ```bash
   git add postgres-dumps/pre-migrated.sql.gz
   git commit -m "Update pre-migrated database dump"
   ```

## When to Regenerate

Regenerate the dump periodically, especially after:

- Many new migrations have been added
- The dump becomes significantly out of date
- You want to optimize the starting point for faster test setup

Since migrations always run after restore, the dump doesn't need to be perfectly up-to-date, but keeping it relatively current provides better performance.

## File Structure

- `pre-migrated.sql.gz` - The compressed database dump (single file, always committed to repo)
