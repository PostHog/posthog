/**
 * Ingestion warning registry — the single source of truth for every warning type
 * this platform emits, shared across the Node.js pipeline and, via codegen, the
 * Rust producers (the whole registry is exported to
 * `rust/common/ingestion_warnings/warning_types.generated.json`, from which the
 * Rust `WarningType` enum is generated).
 *
 * This module is intentionally dependency-free (pure data + types): it can be
 * imported by the standalone generator (`bin/generate-ingestion-warning-types.mts`)
 * and the no-drift test without loading the ingestion runtime. The runtime helpers
 * (serialize/emit, Kafka producer wiring) live in `./ingestion-warnings.ts`, which
 * re-exports everything here so existing `~/ingestion/common/ingestion-warnings`
 * importers are unaffected.
 */

export type IngestionWarningCategory = 'size' | 'merge' | 'event' | 'transformation' | 'replay' | 'quota'
export type IngestionWarningSeverity = 'info' | 'warning' | 'error'

/**
 * Central registry of every ingestion warning type this service can emit.
 * Category and severity are fixed attributes of the type, resolved at
 * serialization time so callsites cannot drift or forget them. Adding a new
 * warning requires registering it here, which keeps the ClickHouse v2
 * structured columns, the API filters, and agent-facing docs in sync.
 *
 * Severity convention: 'error' = the event (or message) was dropped,
 * 'warning' = ingested but modified or partially rejected,
 * 'info' = informational or an intentional, team-configured drop.
 */
export const INGESTION_WARNING_TYPES = {
    // Size limits — payload or property blobs exceeding Kafka/Postgres limits
    // captureProduced: capture's Kafka sink hits the same MessageSizeTooLarge
    // limit this pipeline reports at emit time, so both producers share the type.
    message_size_too_large: { category: 'size', severity: 'error', captureProduced: true },
    // The personhog leader trimmed or rejected a person property update at
    // admission to fit the Postgres size constraint.
    person_properties_size_violation: { category: 'size', severity: 'error' },
    person_upsert_message_size_too_large: { category: 'size', severity: 'error' },
    group_upsert_message_size_too_large: { category: 'size', severity: 'error' },
    group_key_too_long: { category: 'size', severity: 'error' },

    // Person merges — rejected $identify / $create_alias / $merge_dangerously operations
    cannot_merge_already_identified: { category: 'merge', severity: 'warning' },
    cannot_merge_with_illegal_distinct_id: { category: 'merge', severity: 'warning' },
    merge_race_condition: { category: 'merge', severity: 'error' },

    // Event validation — malformed or rejected event data
    client_ingestion_warning: { category: 'event', severity: 'info' },
    // Capture-side validation drops (Rust capture; see rust/common/ingestion_warnings/src/registry.rs).
    // `captureProduced: true` marks the types capture may set via the structured envelope property —
    // it derives the CAPTURE_PRODUCED_WARNING_TYPES trust allowlist below.
    missing_event_name: { category: 'event', severity: 'error', captureProduced: true },
    event_name_too_long: { category: 'event', severity: 'error', captureProduced: true },
    missing_distinct_id: { category: 'event', severity: 'error', captureProduced: true },
    distinct_id_too_large: { category: 'event', severity: 'error', captureProduced: true },
    // Legacy capture ingests the event after cutting the distinct_id down to
    // the 200-char cap (v1 drops it instead, as distinct_id_too_large above).
    distinct_id_truncated: { category: 'event', severity: 'warning', captureProduced: true },
    invalid_event_timestamp: { category: 'event', severity: 'error', captureProduced: true },
    malformed_event_properties: { category: 'event', severity: 'error', captureProduced: true },
    invalid_options: { category: 'event', severity: 'error', captureProduced: true },
    empty_batch: { category: 'event', severity: 'error', captureProduced: true },
    invalid_batch: { category: 'event', severity: 'error', captureProduced: true },
    missing_event_uuid: { category: 'event', severity: 'error', captureProduced: true },
    invalid_event_uuid: { category: 'event', severity: 'error', captureProduced: true },
    duplicate_event_uuid: { category: 'event', severity: 'error', captureProduced: true },
    // Capture's AI endpoints (/i/v0/ai, /i/v0/ai/otel), which validate more
    // strictly than the analytics paths: they accept only the six `$ai_*` event
    // names and require `$ai_model`, and their payloads are multipart or OTLP
    // rather than a JSON batch.
    invalid_ai_event: { category: 'event', severity: 'error', captureProduced: true },
    invalid_ai_payload: { category: 'event', severity: 'error', captureProduced: true },
    // Severity is 'warning', not 'error': the OTLP export succeeded and only
    // non-AI spans were in it, so nothing the AI pipeline owns was dropped. The
    // customer still needs to know their export produced no AI events.
    no_ai_spans_ingested: { category: 'event', severity: 'warning', captureProduced: true },
    ignored_invalid_timestamp: { category: 'event', severity: 'warning' },
    schema_validation_failed: { category: 'event', severity: 'error' },
    skipping_event_invalid_distinct_id: { category: 'event', severity: 'error' },
    invalid_ai_token_property: { category: 'event', severity: 'warning' },
    invalid_group_set: { category: 'event', severity: 'error' },
    invalid_process_person_profile: { category: 'event', severity: 'warning' },
    invalid_event_when_process_person_profile_is_false: { category: 'event', severity: 'error' },
    event_dropped_too_old: { category: 'event', severity: 'info' },

    // Cookieless mode — events missing the data required to compute a cookieless distinct id
    cookieless_missing_timestamp: { category: 'event', severity: 'error' },
    cookieless_timestamp_out_of_range: { category: 'event', severity: 'error' },
    cookieless_missing_user_agent: { category: 'event', severity: 'error' },
    cookieless_missing_ip: { category: 'event', severity: 'error' },
    cookieless_missing_host: { category: 'event', severity: 'error' },

    // Heatmaps — rejected $heatmap_data payloads
    invalid_heatmap_data: { category: 'event', severity: 'warning' },
    rejecting_heatmap_data_with_invalid_url: { category: 'event', severity: 'warning' },
    rejecting_heatmap_data_with_invalid_items: { category: 'event', severity: 'warning' },

    // Error tracking — exception event processing
    error_tracking_exception_processing_errors: { category: 'event', severity: 'warning' },

    // Quota and rate limiting — platform-imposed limits, not team-configured ones.
    // Severity is 'warning' rather than 'error' because nothing is dropped: the
    // event is ingested with person profile processing turned off and rerouted to
    // overflow. See `apply_token_distinct_id_limits` in rust/capture.
    high_volume_distinct_id: { category: 'quota', severity: 'warning', captureProduced: true },

    // Transformations — user-configured hog transformations
    event_dropped_by_transformation: { category: 'transformation', severity: 'info' },

    // Session replay — rejected or suspicious replay messages
    replay_lib_version_too_old: { category: 'replay', severity: 'info' },
    message_contained_no_valid_rrweb_events: { category: 'replay', severity: 'warning' },
    message_timestamp_diff_too_large: { category: 'replay', severity: 'warning' },
    // Capture's replay endpoint (/s), which validates the $snapshot envelope before
    // the batch is collapsed into one $snapshot_items message. Distinguished from the
    // three above by `source: capture` and `path: replay` — those describe conditions
    // found after ingestion, these reject at the edge.
    missing_session_id: { category: 'replay', severity: 'error', captureProduced: true },
    invalid_session_id: { category: 'replay', severity: 'error', captureProduced: true },
    missing_snapshot_data: { category: 'replay', severity: 'error', captureProduced: true },
} as const satisfies Record<
    string,
    {
        category: IngestionWarningCategory
        severity: IngestionWarningSeverity
        captureProduced?: true
    }
>

export type IngestionWarningType = keyof typeof INGESTION_WARNING_TYPES

/**
 * The subset of `INGESTION_WARNING_TYPES` that trusted Rust backend producers
 * (capture; see `rust/common/ingestion_warnings/src/registry.rs`) are allowed to
 * set via the structured `$$client_ingestion_warning_type` property.
 * `$$client_ingestion_warning` events arrive over the public capture path, so
 * that property is attacker-controlled — promoting it to an arbitrary registered
 * type would let a client impersonate any producer and forge details for
 * renderer-only types (e.g. `schema_validation_failed`, whose UI assumes a
 * validated `errors` array shape).
 *
 * Derived from the `captureProduced` flag above rather than hand-listed, so this
 * allowlist can never skew from the registry. The flag is also exported in the
 * generated Rust artifact, where a test welds this set to the union of capture's
 * two emit routes: types derived from an error tag (`from_tag`) and types capture
 * emits directly, with no tag behind them (`DIRECT_EMIT`). Skew in either
 * direction silently drops warnings — a flagged type on neither route is never
 * emitted, and a type on a route without the flag is emitted and then rejected
 * here at the consumer.
 */
export const CAPTURE_PRODUCED_WARNING_TYPES: ReadonlySet<IngestionWarningType> = new Set(
    (Object.entries(INGESTION_WARNING_TYPES) as [IngestionWarningType, { captureProduced?: boolean }][])
        .filter(([, meta]) => meta.captureProduced === true)
        .map(([type]) => type)
)
