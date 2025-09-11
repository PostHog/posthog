pub const UPDATES_ISSUED: &str = "prop_defs_issued_updates";
pub const EVENTS_RECEIVED: &str = "prop_defs_events_received";
pub const EVENTS_SKIPPED: &str = "prop_defs_events_skipped";
pub const FORCED_SMALL_BATCH: &str = "prop_defs_forced_small_batch";
pub const UPDATES_SEEN: &str = "prop_defs_seen_updates";
pub const WORKER_BLOCKED: &str = "prop_defs_worker_blocked";
pub const UPDATES_PER_EVENT: &str = "prop_defs_updates_per_event";
pub const UPDATES_FILTERED_BY_CACHE: &str = "prop_defs_filtered_by_cache";
pub const EMPTY_EVENTS: &str = "prop_defs_empty_events";
pub const EVENT_PARSE_ERROR: &str = "prop_defs_event_parse_error";
pub const BATCH_ACQUIRE_TIME: &str = "prop_defs_batch_acquire_time_ms";
pub const UPDATE_ISSUE_TIME: &str = "prop_defs_update_issue_time_ms";
pub const CACHE_CONSUMED: &str = "prop_defs_cache_space";
pub const UPDATES_CACHE: &str = "prop_defs_updates_cache";
pub const UPDATE_PRODUCER_OFFSET: &str = "prop_defs_update_producer_offset";
pub const GROUP_TYPE_CACHE: &str = "prop_defs_group_type_cache";
pub const RECV_DEQUEUED: &str = "prop_defs_recv_dequeued";
pub const COMPACTED_UPDATES: &str = "prop_defs_compaction_dropped_updates";
pub const CACHE_WARMING_STATE: &str = "prop_defs_cache_state";
pub const UPDATE_TRANSACTION_TIME: &str = "prop_defs_update_transaction_time_ms";
pub const GROUP_TYPE_RESOLVE_TIME: &str = "prop_defs_group_type_resolve_time_ms";
pub const UPDATES_SKIPPED: &str = "prop_defs_skipped_updates";
pub const UPDATES_DROPPED: &str = "prop_defs_dropped_updates";
pub const GROUP_TYPE_READS: &str = "prop_defs_group_type_reads";
pub const SKIPPED_DUE_TO_TEAM_FILTER: &str = "prop_defs_skipped_due_to_team_filter";
pub const ISSUE_FAILED: &str = "prop_defs_issue_failed";
pub const CHUNK_SIZE: &str = "prop_defs_chunk_size";
pub const DUPLICATES_IN_BATCH: &str = "prop_defs_duplicates_in_batch";
pub const SINGLE_UPDATE_ISSUE_TIME: &str = "prop_defs_single_update_issue_time_ms";
pub const CHANNEL_MESSAGES_IN_FLIGHT: &str = "prop_defs_channel_messages_in_flight";
pub const CHANNEL_CAPACITY: &str = "prop_defs_channel_capacity";

pub const ISOLATED_PROPDEFS_DB_SELECTED: &str = "isolated_propdefs_db_selected";

//
// property-defs-rs "v2" batch write path metric keys below
//

pub const V2_EVENT_DEFS_BATCH_WRITE_TIME: &str = "propdefs_v2_eventdefs_batch_ms";
pub const V2_EVENT_DEFS_BATCH_ATTEMPT: &str = "propdefs_v2_eventdefs_batch_attempt";
pub const V2_EVENT_DEFS_BATCH_ROWS_AFFECTED: &str = "propdefs_v2_eventdefs_batch_rows";
pub const V2_EVENT_DEFS_BATCH_CACHE_TIME: &str = "propdefs_v2_eventdefs_batch_cache_time_ms";
pub const V2_EVENT_DEFS_CACHE_REMOVED: &str = "propdefs_v2_eventdefs_cache_removed";
pub const V2_EVENT_DEFS_CACHE_HIT: &str = "propdefs_v2_eventdefs_cache_hit";
pub const V2_EVENT_DEFS_CACHE_MISS: &str = "propdefs_v2_eventdefs_cache_miss";
pub const V2_EVENT_DEFS_BATCH_SIZE: &str = "propdefs_v2_eventdefs_batch_size";

pub const V2_EVENT_PROPS_BATCH_WRITE_TIME: &str = "propdefs_v2_eventprops_batch_ms";
pub const V2_EVENT_PROPS_BATCH_ATTEMPT: &str = "propdefs_v2_eventprops_batch_attempt";
pub const V2_EVENT_PROPS_BATCH_ROWS_AFFECTED: &str = "propdefs_v2_eventprops_batch_rows";
pub const V2_EVENT_PROPS_BATCH_CACHE_TIME: &str = "propdefs_v2_eventprops_batch_cache_time_ms";
pub const V2_EVENT_PROPS_CACHE_REMOVED: &str = "propdefs_v2_eventprops_cache_removed";
pub const V2_EVENT_PROPS_CACHE_HIT: &str = "propdefs_v2_eventprops_cache_hit";
pub const V2_EVENT_PROPS_CACHE_MISS: &str = "propdefs_v2_eventprops_cache_miss";
pub const V2_EVENT_PROPS_BATCH_SIZE: &str = "propdefs_v2_eventprops_batch_size";

pub const V2_PROP_DEFS_BATCH_WRITE_TIME: &str = "propdefs_v2_propdefs_batch_ms";
pub const V2_PROP_DEFS_BATCH_ATTEMPT: &str = "propdefs_v2_propdefs_batch_attempt";
pub const V2_PROP_DEFS_BATCH_ROWS_AFFECTED: &str = "propdefs_v2_propdefs_batch_rows";
pub const V2_PROP_DEFS_BATCH_CACHE_TIME: &str = "propdefs_v2_propdefs_batch_cache_time_ms";
pub const V2_PROP_DEFS_CACHE_REMOVED: &str = "propdefs_v2_propdefs_cache_removed";
pub const V2_PROP_DEFS_CACHE_HIT: &str = "propdefs_v2_propdefs_cache_hit";
pub const V2_PROP_DEFS_CACHE_MISS: &str = "propdefs_v2_propdefs_cache_miss";
pub const V2_PROP_DEFS_BATCH_SIZE: &str = "propdefs_v2_propdefs_batch_size";
