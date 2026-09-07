# ClickHouse utility UDFs

`JSONCleanPostHogEventProperties` groups `$feature/<key>` event properties into `$feature_flags`.
Before emitting JSON for insertion, it sorts the keys in `$feature_flags` alphabetically using case-sensitive string order.
This also applies to existing `$feature_flags` objects, after cleanup resolves duplicates and expands dotted keys.
Flag values and person-property ordering follow the existing cleanup rules.

See [the utility UDF README](../../clickhouse-udfs/util/README.md) for build and integration-test commands.

The event, person, and temporary cleaners reuse parser nodes across rows.
Recycled nodes keep small backing arrays for reuse and release larger arrays whose capacity exceeds twice their used length, so a wide row does not make later small rows repeatedly clear oversized arrays.
They clear references across the remaining backing arrays, including entries removed during cleanup, so borrowed property keys do not retain previously processed input rows.

### `JSONCleanPostHogTemporaryProperties(json)`

Accepts a JSON object and retains only the following top-level properties, including their dotted descendants. It uses the event cleaner's dotted-key expansion, null-object-field removal, duplicate handling, and integer protection, without coercing values to declared schema types. Non-object input fails.

| Category                      | Allowlist                                                                                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Person and group instructions | `$set`, `$set_once`, `$unset`, `$group_set`                                                                                                      |
| SDK diagnostics               | Every `$sdk_debug_*` property, including session duration                                                                                        |
| Flag diagnostics              | `$feature_flag_request_id`                                                                                                                       |
| Replay diagnostics            | `$debug_first_full_snapshot_timestamp`, `$snapshot_max_depth_exceeded`, `$sess_rec_flush_size`                                                   |
| Replay configuration          | `$session_recording_remote_config`, `$session_recording_network_payload_capture`, `$session_recording_canvas_recording`, `$replay_script_config` |
| Transport diagnostics         | `$sent_at`, `$lib_rate_limit_remaining_tokens`, `$lib_custom_api_host`                                                                           |

`$feature_flag_request_id` moves to temporary properties on every event type. `$debug_images` remains in permanent properties. Feature-flag payloads and `$active_feature_flags` are excluded from both outputs. Matching applies only at the root: a custom object's nested `$set` is not a temporary property.

Run both cleaners on the original JSON; the event cleaner has already discarded the temporary properties. Apply person/group instructions before splitting stored event properties. Retention belongs to the destination column's TTL and insertion time; this function does not expire data itself.

```sql
WITH '{"$set":{"score":7},"$sdk_debug_probe":true,"$sdk_debug_current_session_duration":42,"$feature_flag_request_id":"request-example","custom":"kept"}' AS raw_properties
SELECT
    JSONCleanPostHogEventProperties(raw_properties) AS properties,
    JSONCleanPostHogTemporaryProperties(raw_properties) AS temporary_properties;
-- properties: {"custom":"kept"}
-- temporary_properties: {"$set":{"score":7},"$sdk_debug_probe":true,"$sdk_debug_current_session_duration":42,"$feature_flag_request_id":"request-example"}
```

Both functions use the same executable. The temporary entry point uses `--temporary-properties` with the existing chunk protocol.

Documents exceeding the shared depth limit produce `{}` in the temporary output; the permanent cleaner quarantines the original document.
