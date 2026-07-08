import { murmur2Partition } from '~/common/kafka/murmur2'
import { logger } from '~/common/utils/logger'

/**
 * Wire shape of a committed `P_old -> P_new` person merge event.
 *
 * This MUST decode by the Rust `PersonMergeEvent` struct in
 * `rust/cohort-stream-processor/src/merge/transfer.rs` (pinned by its
 * `person_merge_event_shape_is_pinned` test). Field names and types are load-bearing: serde reads
 * `team_id` as i32, `merged_at_ms` as i64, `schema_version` as u32, so they must serialize as JSON
 * numbers — stringified numbers are rejected on the Rust side.
 */
export interface PersonMergeKafkaEvent {
    team_id: number
    /** P_old — the person deleted by the merge. Also the partition key. */
    old_person_uuid: string
    /** P_new — the merge target. */
    new_person_uuid: string
    merged_at_ms: number
    schema_version: number
}

/** Mirrors `MERGE_EVENT_SCHEMA_VERSION` in transfer.rs. */
export const MERGE_EVENT_SCHEMA_VERSION = 1

export interface PersonMergeEventMessage {
    key: string
    partition: number
    value: Buffer
}

/**
 * Build the Kafka message for a committed person merge.
 *
 * The key is `"{team_id}:{old_person_uuid}"` (P_old) so the message lands on the worker that owns
 * P_old's Stage-1 state — matches `merge_partition_key` in partitioner.rs.
 *
 * The partition is computed explicitly with Kafka-Java murmur2 rather than left to the producer's
 * default partitioner: (1) librdkafka defaults to CRC32 `consistent_random`, which would route to
 * the wrong worker; (2) node-rdkafka silently discards a global-config `partitioner` key (its
 * client always passes a topicConf to the native ctor, replacing librdkafka's default_topic_conf),
 * so there is no config-only way to switch it.
 */
export function buildPersonMergeEventMessage(
    teamId: number,
    oldPersonUuid: string,
    newPersonUuid: string,
    mergedAtMs: number,
    partitionCount: number
): PersonMergeEventMessage {
    const key = `${teamId}:${oldPersonUuid}`
    const event: PersonMergeKafkaEvent = {
        team_id: teamId,
        old_person_uuid: oldPersonUuid,
        new_person_uuid: newPersonUuid,
        merged_at_ms: mergedAtMs,
        schema_version: MERGE_EVENT_SCHEMA_VERSION,
    }
    return {
        key,
        partition: murmur2Partition(key, partitionCount),
        value: Buffer.from(JSON.stringify(event)),
    }
}

let warnedUnconfiguredMergeEventsTopic = false

/**
 * Effective enable for person_merge_events: the kill switch AND a configured output topic. The topic
 * defaults to '' (unwired), and producing to an empty topic would warn on every gated merge, so an
 * unset topic disables emission. Warns once when the gate is on but the topic is unconfigured. The
 * topic is optional because the ingestion consumer's config type does not surface output topics,
 * though its runtime config always carries one.
 */
export function effectivePersonMergeEventsEnabled(config: {
    PERSON_MERGE_EVENTS_ENABLED: boolean
    INGESTION_OUTPUT_PERSON_MERGE_EVENTS_TOPIC?: string
}): boolean {
    if (!config.PERSON_MERGE_EVENTS_ENABLED) {
        return false
    }
    if (!config.INGESTION_OUTPUT_PERSON_MERGE_EVENTS_TOPIC) {
        if (!warnedUnconfiguredMergeEventsTopic) {
            warnedUnconfiguredMergeEventsTopic = true
            logger.warn(
                'PERSON_MERGE_EVENTS_ENABLED is set but INGESTION_OUTPUT_PERSON_MERGE_EVENTS_TOPIC is empty; not emitting person_merge_events'
            )
        }
        return false
    }
    return true
}
