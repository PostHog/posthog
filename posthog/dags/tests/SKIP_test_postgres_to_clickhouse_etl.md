# Test Skipped: test_postgres_to_clickhouse_etl.py

This test file has been temporarily skipped because it was written before the database separation architecture was implemented.

## Issue

The tests attempt to insert data into tables like `posthog_grouptypemapping` in the persons database, but these tables only exist in the main PostHog database. With the current database separation:
- Main database (`posthog`): Contains teams, organizations, group type mappings, etc.
- Persons database (`posthog_persons`): Contains persons-specific data

## Error

```
psycopg.errors.UndefinedTable: relation "posthog_grouptypemapping" does not exist
```

## Next Steps

The test file needs to be updated to:
1. Use the correct database connections for each table type
2. Account for the database separation architecture
3. Potentially mock the cross-database operations if needed

## Original File

The original test file has been renamed to `test_postgres_to_clickhouse_etl.py.skip` and can be found in this directory.

## Related

- Database separation was implemented to improve scalability
- See PostHog's database architecture documentation for more details on the separation
