# JSONCleanPostHogEvent fixtures

Two TabSeparated columns per row: the raw event properties and the raw person properties. The reference holds the named tuple ClickHouse prints for each row. Blank, malformed, and non-object input must not fail the query; they come back quarantined.
