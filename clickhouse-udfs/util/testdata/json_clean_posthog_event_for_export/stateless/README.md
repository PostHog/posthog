# JSONCleanPostHogEventForExport fixtures

Two TabSeparated columns per row: the raw event properties and the raw person properties. The reference holds the named tuple ClickHouse prints for each row. Each document is the JSON value that a read of the events table returns for the same input, so objects and arrays are JSON, and the temporary properties are also in `properties`. Blank, malformed, non-object, and out-of-range input must not fail the query.
