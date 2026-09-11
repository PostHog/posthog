# Native events query compatibility

The v2 raw-session backfill resolves the events schema once for the selected team.
With the native schema enabled, it reads the session ID and session properties from JSON subcolumns.
It does not serialize the whole properties column.

Declared string paths are cast to `String` so their aggregate states match the session table, including paths stored as `LowCardinality(String)`.
Dynamic string paths use their `String` variant, with an empty string for missing or non-string values.
Viewport dimensions use scalar JSON integer extraction to preserve numeric truncation; web-vital values use nullable float conversion.

An explicit source table keeps the caller's legacy source contract, including its supplied session-ID expression.
The `test_backfill_sql` case checks the generated query, insertion, and decoded aggregate values in both schema modes.

Native AI trace and session IDs use the same comparison optimization as other declared string paths.
Equality and membership filters read the subcolumn directly; projections still convert the empty-string missing-value sentinel to NULL.
Scalar JSON serialization uses the same missing-value conversion, so precomputed breakdowns retain the live query’s NULL row.
The legacy materialized-column exception applies only to legacy sources.
After aggregation, property comparisons retain the grouped expression in `HAVING` and `ORDER BY`; rewriting them to a bare subcolumn can reference a value absent from `GROUP BY`.
Native session, window, and group columns read their JSON subcolumns directly.
This prevents the distributed proxy's computed aliases from colliding with aggregate outputs that use the same names, such as `argMin($session_id, timestamp) AS $session_id`.

Native test event inserts run `JSONCleanPostHogEventProperties` on the input JSON before insertion, matching ingestion's feature-flag map conversion.
Single and bulk inserts share this path; legacy test rows retain their original properties.
The journey fixture uses the same bulk-insert SQL, including native ingestion cleanup and temporary-property routing.
The cleaner runs on fixture values and does not serialize a stored properties column.

Event taxonomy discovery excludes both `$feature/<name>` fields and the native `$feature_flags` map.
When taxonomy discovery enumerates the native JSON document, ClickHouse formats inferred DateTime values with a space between the date and time.
Native shared events omit heavy AI payloads such as `$ai_output_choices`; AI session fallback keeps trace structure, token counts, and costs without those payloads.
AI fallback rewriting preserves query parameter names, including names such as `trace_id` that also identify dedicated columns.
Summarization reports unavailable message content when the dedicated AI row has expired and the shared native row no longer contains that content.
AI credit billing reads tool calls from the dedicated `ai_events.output_state` column to exclude free traces, while cost aggregation continues to read event subcolumns.
Replay capture diagnostics read the fixed diagnostic fields as native subcolumns and preserve SDK debug fields from `temporary_properties` while that column is retained.
The open-ended `$sdk_debug_` prefix requires enumerating the temporary bag for the selected event; regular event properties are never serialized by this lookup.

Custom batch export schemas compile their stored SQL fragments against the legacy events views, matching the export reader and its filters, even when native events are enabled for analytics.

For local batch export tests, `OBJECT_STORAGE_ENDPOINT` is the worker-reachable S3 endpoint and `BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT` is the ClickHouse-reachable endpoint.
The local worker honors the configured endpoint instead of requiring port 19000.

Error search uses the shared case-insensitive array search optimization.
Native exception arrays are searched element by element, so JSON escaping cannot prevent source paths from matching.
Error-tracking eval seeders write to the team's active events schema and use the shared native input normalization, so seeded issues remain queryable with person filters.
