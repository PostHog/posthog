/**
* Types added to this file will be processed into the Plugin Server schema.json file and be available for validation using `ajv`
*/

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
    first_url: string | undefined
    click_count: number
    keypress_count: number
    mouse_activity_count: number
    active_milliseconds: number
    console_log_count: number
    console_warn_count: number
    console_error_count: number
    size: number
}
