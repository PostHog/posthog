/**
 * Types added to this file will be processed into the Plugin Server schema.json file and be available for validation using `ajv`
 */

import { ClickHouseTimestamp } from '../types'

/**
 *
 * written to kafka topic: clickhouse_session_replay_events
 * and from there to clickhouse table: session_replay_events
 */
export interface SummarizedSessionRecordingEvent {
    uuid: string
    first_timestamp: string
    last_timestamp: string
    team_id: number
    distinct_id: string
    session_id: string
    /**
     * @nullable
     * */
    first_url: string | undefined | null
    /**
     * @asType integer
     * */
    click_count: number
    /**
     * @asType integer
     * */
    keypress_count: number
    /**
     * @asType integer
     * */
    mouse_activity_count: number
    /**
     * @asType integer
     * */
    active_milliseconds: number
    /**
     * @asType integer
     * */
    console_log_count: number
    /**
     * @asType integer
     * */
    console_warn_count: number
    /**
     * @asType integer
     * */
    console_error_count: number
    /**
     * @asType integer
     * */
    size: number
    /**
     * @asType integer
     * */
    event_count: number
    /**
     * @asType integer
     * */
    message_count: number
}

export type ConsoleLogEntry = {
    team_id: number
    message: string
    log_level: 'info' | 'warn' | 'error'
    log_source: 'session_replay'
    // the session_id
    log_source_id: string
    // The ClickHouse log_entries table collapses input based on its order by key
    // team_id, log_source, log_source_id, instance_id, timestamp
    // since we don't have a natural instance id, we don't send one.
    // This means that if we can log two messages for one session with the same timestamp
    // we might lose one of them
    // in practice console log timestamps are pretty precise: 2023-10-04 07:53:29.586
    // so, this is unlikely enough that we can avoid filling the DB with UUIDs only to avoid losing
    // a very, very small proportion of console logs.
    instance_id: string | null
    timestamp: ClickHouseTimestamp
}
